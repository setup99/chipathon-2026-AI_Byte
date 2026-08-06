# =============================================================================
#  test_softmax_serial_full_q88.py
#  test_softmax_rtn_full_q88.py's battery (uniform, peaked, ramp,
#  sum-to-one, latency, large-range, each repeated for N=2..8),
#  adapted for eml_softmax_q88_serial's fully-serial interface:
#  push logits one per cycle via z_in/z_valid, collect results one
#  per cycle via result/result_valid, instead of packed buses.
# =============================================================================

import math
import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"
W = 16
F = 8
SCALE = 1 << F
Q88_MAX = 127.99609375
Q88_MIN = -128.0
N_RANGE = [2, 3, 4, 5, 6, 7, 8]


def float_to_q88(val: float) -> int:
    if val >= Q88_MAX:
        return 0x7FFF
    if val <= Q88_MIN:
        return 0x8000
    raw = round(val * SCALE)
    raw = max(-(1 << 15), min((1 << 15) - 1, raw))
    return raw & 0xFFFF


def q88_to_float(raw) -> float:
    raw = int(raw) & 0xFFFF
    if raw >= 0x8000:
        raw -= 0x10000
    return raw / SCALE


def true_softmax(z):
    m = max(z)
    exps = [math.exp(v - m) for v in z]
    s = sum(exps)
    return [e / s for e in exps]


def linspace(a, b, n):
    if n == 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


def fmt_vec(vec):
    return "[" + ", ".join(f"{v:+.4f}" for v in vec) + "]"


def log_case(dut, label, zs, got, ref=None):
    dut._log.info(f"    {label}")
    dut._log.info(f"      z    = {fmt_vec(zs)}")
    dut._log.info(f"      got  = {fmt_vec(got)}")
    if ref is not None:
        dut._log.info(f"      ref  = {fmt_vec(ref)}")
        diffs = [g - r for g, r in zip(got, ref)]
        dut._log.info(f"      diff = {fmt_vec(diffs)}")


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.n_in.value = 0
    dut.z_in.value = 0
    dut.z_valid.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def run_softmax_serial(dut, n, zs, gap_cycles=0, timeout=400):
    """Push n logits one per cycle (optionally with gaps between
    pushes, to test that the FSM correctly waits on z_valid), then
    collect n results one per cycle as they stream out. `cycles`
    returned here is the TRUE total start->valid latency, including
    the push phase -- not just the post-push segment."""
    dut.n_in.value = n
    await RisingEdge(dut.clk)
    dut.start.value = 1
    cycles = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0

    for z in zs:
        if gap_cycles:
            dut.z_valid.value = 0
            await ClockCycles(dut.clk, gap_cycles)
            cycles += gap_cycles
        dut.z_in.value = float_to_q88(z)
        dut.z_valid.value = 1
        await RisingEdge(dut.clk)
        cycles += 1
    dut.z_valid.value = 0
    dut.z_in.value = 0

    results = []
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.result_valid.value) == 1:
            results.append(q88_to_float(dut.result.value))
        if int(dut.valid.value) == 1:
            break
    else:
        raise AssertionError(f"Timed out waiting for valid (N={n}, z={zs})")

    assert len(results) == n, f"expected {n} streamed results, got {len(results)}"
    return results, cycles, int(dut.ovf.value)


@cocotb.test()
async def test_serial_uniform_all_n(dut):
    """Uniform logits [1,1,...,1] -> all outputs should be ~1/N, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SERIAL SOFTMAX -- uniform [1]*N for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = [1.0] * n
        got, cycles, ovf = await run_softmax_serial(dut, n, zs)
        expect = 1.0 / n
        worst = max(abs(v - expect) for v in got)
        s = sum(got)
        ok = worst < 0.05 and abs(s - 1.0) < 0.08
        if not ok:
            fails += 1
        dut._log.info(f"  N={n}: worst_err={worst:.4f}  sum={s:.4f}  cycles={cycles}  {'ok' if ok else 'FAIL'}")
        log_case(dut, f"N={n} values", zs, got, [expect] * n)
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed uniform check"
    dut._log.info("PASS test_serial_uniform_all_n")


@cocotb.test()
async def test_serial_peaked_all_n(dut):
    """Peaked logits [2,0,0,...,0] -> element 0 should dominate, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SERIAL SOFTMAX -- peaked [2,0,...,0] for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = [2.0] + [0.0] * (n - 1)
        got, cycles, ovf = await run_softmax_serial(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = sum(
            1 for v, r in zip(got, ref)
            if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03)
        )
        dut._log.info(f"  N={n}: cycles={cycles}  elem_fails={elem_fails}  {'ok' if elem_fails == 0 else 'FAIL'}")
        log_case(dut, f"N={n} values", zs, got, ref)
        if elem_fails:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed peaked check"
    dut._log.info("PASS test_serial_peaked_all_n")


@cocotb.test()
async def test_serial_ramp_all_n(dut):
    """Monotonic ramp logits, linspace(-1,2,N), for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SERIAL SOFTMAX -- ramp linspace(-1,2,N) for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = linspace(-1.0, 2.0, n)
        got, cycles, ovf = await run_softmax_serial(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = sum(
            1 for v, r in zip(got, ref)
            if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03)
        )
        dut._log.info(f"  N={n}: cycles={cycles}  elem_fails={elem_fails}  {'ok' if elem_fails == 0 else 'FAIL'}")
        log_case(dut, f"N={n} values", zs, got, ref)
        if elem_fails:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed ramp check"
    dut._log.info("PASS test_serial_ramp_all_n")


@cocotb.test()
async def test_serial_sum_to_one_all_n(dut):
    """Random logit vectors -- every softmax output must sum to ~1.0, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    random.seed(42)

    dut._log.info("=" * 78)
    dut._log.info("SERIAL SOFTMAX -- sum-to-one, 8 random vectors per N, N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        n_fails = 0
        for trial in range(8):
            zs = [random.uniform(-2.0, 2.0) for _ in range(n)]
            got, cycles, ovf = await run_softmax_serial(dut, n, zs)
            s = sum(got)
            trial_ok = abs(s - 1.0) < 0.07
            if not trial_ok:
                n_fails += 1
            log_case(dut, f"N={n} trial={trial} sum={s:.4f} {'ok' if trial_ok else 'FAIL'}", zs, got)
        dut._log.info(f"  N={n}: {8 - n_fails}/8 trials passed")
        if n_fails:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values had sum-to-one failures"
    dut._log.info("PASS test_serial_sum_to_one_all_n")


@cocotb.test()
async def test_serial_latency_all_n(dut):
    """Measure TRUE total cycles = start->valid for every N (back-to-
    back pushes, no gaps). Fits and reports the actual formula rather
    than assuming the old parallel-input 8N+3 still applies."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SERIAL SOFTMAX -- TRUE total latency for every N in 2..8 (back-to-back push)")
    dut._log.info("=" * 78)

    measured = {}
    for n in N_RANGE:
        got, cycles, _ = await run_softmax_serial(dut, n, [1.0] * n)
        measured[n] = cycles
        dut._log.info(f"  N={n}: cycles={cycles}")
        log_case(dut, f"N={n} values", [1.0] * n, got, [1.0 / n] * n)

    ns = list(measured.keys())
    cyc = [measured[n] for n in ns]
    a = (cyc[-1] - cyc[0]) / (ns[-1] - ns[0])
    b = cyc[0] - a * ns[0]
    dut._log.info(f"  Fitted latency formula: cycles = {a:.1f}*N + {b:.1f}  (expect 11*N + 3)")
    for n in ns:
        predicted = a * n + b
        assert abs(predicted - measured[n]) < 0.5, f"N={n} doesn't fit the linear model: measured={measured[n]}, fit={predicted}"
    assert abs(a - 11.0) < 0.01 and abs(b - 3.0) < 0.5, f"formula drifted from the expected 11*N+3: got {a:.1f}*N+{b:.1f}"
    dut._log.info("PASS test_serial_latency_all_n")


@cocotb.test()
async def test_serial_large_range_all_n(dut):
    """Logit spread of 3 (linspace(3,0,N)), for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SERIAL SOFTMAX -- large range linspace(3,0,N) for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = linspace(3.0, 0.0, n)
        got, cycles, ovf = await run_softmax_serial(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = sum(
            1 for v, r in zip(got, ref)
            if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03)
        )
        ok = elem_fails == 0 and ovf == 0
        dut._log.info(f"  N={n}: cycles={cycles}  ovf={ovf}  elem_fails={elem_fails}  {'ok' if ok else 'FAIL'}")
        log_case(dut, f"N={n} values", zs, got, ref)
        if not ok:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed large-range check"
    dut._log.info("PASS test_serial_large_range_all_n")


@cocotb.test()
async def test_serial_gapped_push(dut):
    """Confirm the FSM correctly waits through gaps in z_valid (a
    producer that isn't always ready) instead of assuming back-to-back
    pushes -- something the old parallel-bus interface had no notion
    of at all."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SERIAL SOFTMAX -- gapped push (producer stalls between logits)")
    dut._log.info("=" * 78)

    zs = [1.0, 0.5, -0.5, -1.0]
    got, cycles, ovf = await run_softmax_serial(dut, 4, zs, gap_cycles=3)
    ref = true_softmax(zs)
    elem_fails = sum(
        1 for v, r in zip(got, ref)
        if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03)
    )
    dut._log.info(f"  z={zs}  got={[f'{v:.4f}' for v in got]}  cycles={cycles}  elem_fails={elem_fails}")
    log_case(dut, "gapped push values", zs, got, ref)
    assert elem_fails == 0, "gapped push produced a wrong result -- FSM isn't correctly waiting on z_valid"
    dut._log.info("PASS test_serial_gapped_push")