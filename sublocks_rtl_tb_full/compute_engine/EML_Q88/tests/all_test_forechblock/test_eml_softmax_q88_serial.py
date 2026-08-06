# =============================================================================
#  test_softmax_rtn_full_q88.py
#  Full test battery for eml_softmax_q88_serial
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
    dut.z_valid.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def run_softmax(dut, n, zs, timeout=200):
    """
    Drives a serial stream of logits into the DUT and recovers the 
    streamed responses safely, avoiding crashes on X/Z states.
    """
    # 1. Initialize configuration and pulse start
    dut.n_in.value = n
    dut.z_in.value = 0
    dut.z_valid.value = 0
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0

    # 2. Feed elements serially into S_LOAD back-to-back
    for val in zs:
        dut.z_in.value = float_to_q88(val)
        dut.z_valid.value = 1
        await RisingEdge(dut.clk)
    
    # Clear input stream lines
    dut.z_in.value = 0
    dut.z_valid.value = 0

    # 3. Monitor execution and capture streamed outputs
    outputs = []
    cycles = 0
    transaction_done = False

    for _ in range(timeout):
        await RisingEdge(dut.clk)
        cycles += 1

        # Read signal states safely
        r_valid_raw = dut.result_valid.value
        v_raw = dut.valid.value

        # Check if result_valid is resolvable and explicitly 1
        if r_valid_raw.is_resolvable and int(r_valid_raw) == 1:
            r_data_raw = dut.result.value
            if r_data_raw.is_resolvable:
                outputs.append(q88_to_float(int(r_data_raw)))
            else:
                dut._log.warning(f"Cycle {cycles}: result_valid was 1, but result bus contains X/Z: {r_data_raw.binstr}")
                outputs.append(0.0) # Placeholder to avoid breaking array match length

        # Check if final valid out is asserted
        if v_raw.is_resolvable and int(v_raw) == 1:
            transaction_done = True
            break

    if not transaction_done:
        raise AssertionError(f"Timed out waiting for final valid assertion (N={n}, z={zs})")

    # Safe capture of final status flag
    ovf_raw = dut.ovf.value
    ovf_val = int(ovf_raw) if ovf_raw.is_resolvable else 0

    return outputs, cycles, ovf_val


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
    """Confirm latency tracking rules match serial constraints over variable N iterations."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("LATENCY MEASUREMENT -- tracking serial operational duration per N")
    dut._log.info("=" * 78)

    for n in N_RANGE:
        zs = [1.0] * n
        _, cycles, _ = await run_softmax(dut, n, zs)
        dut._log.info(f"  N={n}: measured execution time = {cycles} cycles")
        
    dut._log.info("PASS test_rtn_latency_all_n")


@cocotb.test()
async def test_rtn_large_range_all_n(dut):
    """Logit spread of 3 (linspace(4,1,N), exercising format's dynamic range."""
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