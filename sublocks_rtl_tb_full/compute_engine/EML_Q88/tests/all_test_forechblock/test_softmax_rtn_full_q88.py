# =============================================================================
#  test_softmax_rtn_full_q88.py
#  Full test battery for eml_softmax_q88_rtn -- the same test shapes as
#  test_softmax_q88.py (uniform, peaked, ramp, sum-to-one, latency,
#  large-range), each repeated for every N in {2..8}, all on ONE DUT
#  instance with no reset or recompile between N values -- that's the
#  actual point of the runtime-N design.
#
#  Test-vector generators are parameterized so every N gets a comparable
#  logit shape rather than reusing the fixed N=4 vectors verbatim:
#    uniform     : [1.0] * N
#    peaked      : [2.0, 0, 0, ..., 0]                 (N-1 zeros)
#    ramp        : linspace(-1.0, 2.0, N)               (same endpoints as N=4 original)
#    large_range : linspace(4.0, 1.0, N)                (same endpoints/spread as N=4 original)
#    sum_to_one  : 8 random vectors, uniform(-2, 2), length N
#
#  Tolerances are the same as the original N=4 suite; nothing was
#  loosened for larger N without first checking whether it was needed.
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
    if math.isnan(val):
        return 0
    if val >= Q88_MAX:
        return 0x7FFF
    if val <= Q88_MIN:
        return 0x8000
    raw = round(val * SCALE)
    raw = max(-(1 << 15), min((1 << 15) - 1, raw))
    return raw & 0xFFFF


def q88_to_float(raw: int) -> float:
    raw = int(raw) & 0xFFFF
    if raw >= 0x8000:
        raw -= 0x10000
    return raw / SCALE


def pack_z(zs):
    raw = 0
    for i, v in enumerate(zs):
        raw |= (float_to_q88(v) & 0xFFFF) << (i * W)
    return raw


def unpack_result(raw, n):
    mask = (1 << W) - 1
    return [q88_to_float((raw >> (i * W)) & mask) for i in range(n)]


def true_softmax(z):
    m = max(z)
    exps = [math.exp(v - m) for v in z]
    s = sum(exps)
    return [e / s for e in exps]


def linspace(a, b, n):
    if n == 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.n_in.value = 0
    dut.z_in.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def run_softmax(dut, n, zs, timeout=120):
    dut.n_in.value = n
    dut.z_in.value = pack_z(zs)
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    cycles = 0
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.valid.value) == 1:
            return unpack_result(int(dut.result.value), n), cycles, int(dut.ovf.value)
    raise AssertionError(f"Timed out waiting for valid (N={n}, z={zs})")


@cocotb.test()
async def test_rtn_uniform_all_n(dut):
    """Uniform logits [1,1,...,1] -> all outputs should be ~1/N, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("UNIFORM -- [1]*N for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = [1.0] * n
        got, cycles, ovf = await run_softmax(dut, n, zs)
        expect = 1.0 / n
        worst = max(abs(v - expect) for v in got)
        s = sum(got)
        ok = worst < 0.05 and abs(s - 1.0) < 0.08
        if not ok:
            fails += 1
        dut._log.info(
            f"  N={n}: {[f'{v:.4f}' for v in got]}  expect={expect:.4f}  "
            f"worst_err={worst:.4f}  sum={s:.4f}  cycles={cycles}  {'ok' if ok else 'FAIL'}"
        )
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed uniform check"
    dut._log.info("PASS test_rtn_uniform_all_n")


@cocotb.test()
async def test_rtn_peaked_all_n(dut):
    """Peaked logits [2,0,0,...,0] -> element 0 should dominate, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("PEAKED -- [2,0,...,0] for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = [2.0] + [0.0] * (n - 1)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = 0
        for i, (v, r) in enumerate(zip(got, ref)):
            ae = abs(v - r)
            re = ae / max(abs(r), 1e-6)
            ok = re < 0.08 or ae < 0.03
            if not ok:
                elem_fails += 1
        dut._log.info(
            f"  N={n}: got={[f'{v:.4f}' for v in got]}  ref={[f'{r:.4f}' for r in ref]}  "
            f"cycles={cycles}  elem_fails={elem_fails}  {'ok' if elem_fails == 0 else 'FAIL'}"
        )
        if elem_fails:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed peaked check"
    dut._log.info("PASS test_rtn_peaked_all_n")


@cocotb.test()
async def test_rtn_ramp_all_n(dut):
    """Monotonic ramp logits, linspace(-1,2,N), for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("RAMP -- linspace(-1, 2, N) for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = linspace(-1.0, 2.0, n)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = 0
        for i, (v, r) in enumerate(zip(got, ref)):
            ae = abs(v - r)
            re = ae / max(abs(r), 1e-6)
            ok = re < 0.08 or ae < 0.03
            if not ok:
                elem_fails += 1
        dut._log.info(
            f"  N={n}: z={[f'{z:.2f}' for z in zs]}  got={[f'{v:.4f}' for v in got]}  "
            f"cycles={cycles}  elem_fails={elem_fails}  {'ok' if elem_fails == 0 else 'FAIL'}"
        )
        if elem_fails:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed ramp check"
    dut._log.info("PASS test_rtn_ramp_all_n")


@cocotb.test()
async def test_rtn_sum_to_one_all_n(dut):
    """Random logit vectors -- every softmax output must sum to ~1.0, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    random.seed(42)

    dut._log.info("=" * 78)
    dut._log.info("SUM-TO-ONE -- 8 random vectors per N, for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        n_fails = 0
        for trial in range(8):
            zs = [random.uniform(-2.0, 2.0) for _ in range(n)]
            got, cycles, ovf = await run_softmax(dut, n, zs)
            s = sum(got)
            err = abs(s - 1.0)
            ok = err < 0.07
            if not ok:
                n_fails += 1
            dut._log.info(f"  N={n} trial {trial}: sum={s:.5f}  err={err:.4f}  {'ok' if ok else 'FAIL'}")
        if n_fails:
            fails += 1
        dut._log.info(f"  N={n}: {8 - n_fails}/8 trials passed")
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values had sum-to-one failures"
    dut._log.info("PASS test_rtn_sum_to_one_all_n")


@cocotb.test()
async def test_rtn_latency_all_n(dut):
    """Confirm cycles = 8*N + 3 holds for every N, back-to-back, no reset."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("LATENCY -- cycles = 8*N+3 for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = [1.0] * n
        _, cycles, _ = await run_softmax(dut, n, zs)
        expected = 8 * n + 3
        ok = cycles == expected
        if not ok:
            fails += 1
        dut._log.info(f"  N={n}: cycles={cycles}  expected={expected}  {'ok' if ok else 'FAIL'}")
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values had wrong latency"
    dut._log.info("PASS test_rtn_latency_all_n")


@cocotb.test()
async def test_rtn_large_range_all_n(dut):
    """Logit spread of 3 (linspace(4,1,N), same endpoints as the N=4
    original), exercising the format's dynamic range, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("LARGE RANGE -- linspace(4, 1, N) for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = linspace(4.0, 1.0, n)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = 0
        for i, (v, r) in enumerate(zip(got, ref)):
            ae = abs(v - r)
            re = ae / max(abs(r), 1e-6)
            ok = re < 0.08 or ae < 0.03
            if not ok:
                elem_fails += 1
        dut._log.info(
            f"  N={n}: z={[f'{z:.2f}' for z in zs]}  got={[f'{v:.4f}' for v in got]}  "
            f"ovf={ovf}  cycles={cycles}  elem_fails={elem_fails}  {'ok' if elem_fails == 0 and ovf == 0 else 'FAIL'}"
        )
        if elem_fails or ovf:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed large-range check"
    dut._log.info("PASS test_rtn_large_range_all_n")
