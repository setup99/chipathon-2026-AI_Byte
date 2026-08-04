# =============================================================================
#  test_softmax_q88.py
#  cocotb testbench for eml_softmax_q88 (N=4, lightweight Q8.8 variant)
#
#  Same 6-test structure as test_softmax_q824_v2.py. Tolerances loosened
#  where the coarser 1/256 resolution makes the Q8.24 bar unrealistic;
#  each loosened bound is flagged in place rather than silently copied.
# =============================================================================

import math
import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"

W = 16
F = 8
N = 4
SCALE = 1 << F
Q88_MAX = 127.99609375
Q88_MIN = -128.0


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


def pack_z(z0, z1, z2, z3) -> int:
    v0 = float_to_q88(z0)
    v1 = float_to_q88(z1)
    v2 = float_to_q88(z2)
    v3 = float_to_q88(z3)
    return v0 | (v1 << W) | (v2 << (2 * W)) | (v3 << (3 * W))


def unpack_result(raw: int):
    mask = (1 << W) - 1
    out = []
    for i in range(N):
        out.append(q88_to_float((raw >> (i * W)) & mask))
    return out


def true_softmax(z):
    m = max(z)
    exps = [math.exp(v - m) for v in z]
    s = sum(exps)
    return [e / s for e in exps]


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.z_in.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def run_softmax(dut, z0, z1, z2, z3, timeout=60):
    dut.z_in.value = pack_z(z0, z1, z2, z3)
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    cycles = 0
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.valid.value) == 1:
            result = unpack_result(int(dut.result.value))
            return result, cycles, int(dut.ovf.value)
    raise AssertionError(f"Timed out waiting for valid (z={[z0,z1,z2,z3]})")


@cocotb.test()
async def test_softmax_uniform(dut):
    """Uniform logits [1,1,1,1] -> all outputs should be ~0.25."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    got, cycles, ovf = await run_softmax(dut, 1.0, 1.0, 1.0, 1.0)
    dut._log.info(f"softmax([1,1,1,1]) = {[f'{v:.4f}' for v in got]}  cycles={cycles}")

    fails = 0
    for i, v in enumerate(got):
        err = abs(v - 0.25)
        # loosened from 0.02 (Q8.24) -- 1/256 quantisation alone is ~0.004,
        # plus compound Mitchell error through 3 EML passes
        if err > 0.04:
            fails += 1
        dut._log.info(f"  elem[{i}] = {v:.5f}  expected=0.25000  err={err:.4f}")
    s = sum(got)
    dut._log.info(f"  sum = {s:.5f}")
    assert fails == 0, f"{fails} uniform elements out of tolerance"
    assert abs(s - 1.0) < 0.06   # loosened from 0.03 (Q8.24)
    dut._log.info("PASS test_softmax_uniform")


@cocotb.test()
async def test_softmax_peaked(dut):
    """Peaked logits [2,0,0,0] -> z0 should dominate."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    z = [2.0, 0.0, 0.0, 0.0]
    got, cycles, ovf = await run_softmax(dut, *z)
    ref = true_softmax(z)
    dut._log.info(f"softmax({z}) = {[f'{v:.4f}' for v in got]}  cycles={cycles}")

    fails = 0
    for i, (v, r) in enumerate(zip(got, ref)):
        ae = abs(v - r)
        re = ae / max(abs(r), 1e-6)
        ok = re < 0.08 or ae < 0.03   # loosened from 0.03/0.01 (Q8.24)
        if not ok:
            fails += 1
        dut._log.info(f"  elem[{i}] = {v:.5f}  ref={r:.5f}  rel={re:.3%}  {'ok' if ok else 'FAIL'}")
    assert fails == 0, f"{fails} peaked elements out of tolerance"
    dut._log.info("PASS test_softmax_peaked")


@cocotb.test()
async def test_softmax_ramp(dut):
    """Monotonic ramp logits [-1,0,1,2]."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    z = [-1.0, 0.0, 1.0, 2.0]
    got, cycles, ovf = await run_softmax(dut, *z)
    ref = true_softmax(z)
    dut._log.info(f"softmax({z}) = {[f'{v:.4f}' for v in got]}  cycles={cycles}")

    fails = 0
    for i, (v, r) in enumerate(zip(got, ref)):
        ae = abs(v - r)
        re = ae / max(abs(r), 1e-6)
        ok = re < 0.08 or ae < 0.03
        if not ok:
            fails += 1
        dut._log.info(f"  elem[{i}] = {v:.5f}  ref={r:.5f}  rel={re:.3%}  {'ok' if ok else 'FAIL'}")
    assert fails == 0, f"{fails} ramp elements out of tolerance"
    dut._log.info("PASS test_softmax_ramp")


@cocotb.test()
async def test_softmax_sum_to_one(dut):
    """Random logit vectors -- every softmax output must sum to ~1.0."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    random.seed(42)

    dut._log.info("SUM-TO-ONE check across 8 random vectors")
    fails = 0
    for trial in range(8):
        z = [random.uniform(-2.0, 2.0) for _ in range(4)]
        got, cycles, ovf = await run_softmax(dut, *z)
        s = sum(got)
        err = abs(s - 1.0)
        ok = err < 0.07   # loosened from 0.04 (Q8.24)
        if not ok:
            fails += 1
        dut._log.info(
            f"  trial {trial}: z={[f'{v:.2f}' for v in z]}  sum={s:.5f}  "
            f"err={err:.4f}  {'ok' if ok else 'FAIL'}"
        )
    assert fails == 0, f"{fails}/8 trials failed sum-to-one check"
    dut._log.info("PASS test_softmax_sum_to_one")


@cocotb.test()
async def test_softmax_latency(dut):
    """Confirm FSM latency matches the measured baseline (same FSM as Q8.24: 35 cycles)."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    _, cycles, _ = await run_softmax(dut, 1.0, 0.5, -0.5, -1.0)
    dut._log.info(f"Latency: {cycles} cycles after start pulse")
    # Same FSM state graph as eml_softmax_q824_v2 -- word width does not
    # change cycle count, only data width, so 35 is the expected value
    # here too. Asserted against the measured result, not assumed.
    assert cycles == 35, (
        f"Expected 35-cycle latency (same FSM as Q8.24 design), got {cycles}."
    )
    dut._log.info("PASS test_softmax_latency")


@cocotb.test()
async def test_softmax_large_range(dut):
    """Logit differences up to 4.5 -- exercises the format's dynamic range."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("LARGE RANGE -- logit diff up to 4.5")
    z = [4.0, 3.0, 2.0, 1.0]
    got, cycles, ovf = await run_softmax(dut, *z)
    ref = true_softmax(z)
    dut._log.info(f"softmax({z}) = {[f'{v:.4f}' for v in got]}")

    fails = 0
    for i, (v, r) in enumerate(zip(got, ref)):
        ae = abs(v - r)
        re = ae / max(abs(r), 1e-6)
        ok = re < 0.08 or ae < 0.03
        if not ok:
            fails += 1
        dut._log.info(f"  elem[{i}] = {v:.5f}  ref={r:.5f}  rel={re:.3%}  {'ok' if ok else 'FAIL'}")
    assert ovf == 0, "Should not overflow within Q8.8 range"
    assert fails == 0, f"{fails} large-range elements out of tolerance"
    dut._log.info("PASS test_softmax_large_range")
