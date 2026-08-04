# =============================================================================
#  test_sqrt_q88.py
#  cocotb testbench for eml_sqrt_q88 (sqrt(x), Q8.8, 2-pass FSM)
# =============================================================================

import math
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"

W = 16
F = 8
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


def q88_to_float(raw) -> float:
    raw = int(raw) & 0xFFFF
    if raw >= 0x8000:
        raw -= 0x10000
    return raw / SCALE


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.x_in.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def run_sqrt(dut, x: float, timeout=20):
    dut.x_in.value = float_to_q88(x)
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    cycles = 0
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.valid.value) == 1:
            return q88_to_float(dut.result.value), cycles, int(dut.ovf.value)
    raise AssertionError(f"Timed out waiting for valid (x={x})")


@cocotb.test()
async def test_sqrt_basic(dut):
    """sqrt(1.0) = 1.0 exactly -- ln(1)=0 exact, exp(0)=1 exact, halving 0/2=0 exact."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    got, cycles, ovf = await run_sqrt(dut, 1.0)
    dut._log.info(f"sqrt(1.0) = {got:.6f}  (cycles={cycles}, ovf={ovf})")
    assert abs(got - 1.0) < 1e-3, f"sqrt(1.0) should be ~1.0, got {got}"
    assert ovf == 0
    dut._log.info("PASS test_sqrt_basic")


@cocotb.test()
async def test_sqrt_perfect_squares(dut):
    """sqrt of perfect squares: 4, 9, 16, 25, 36, 49, 64 -- exercises exact powers of 2 too."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 60)
    dut._log.info("SQRT Q8.8 -- PERFECT SQUARES")
    dut._log.info("=" * 60)

    squares = [4.0, 9.0, 16.0, 25.0, 36.0, 49.0, 64.0]
    fails = 0
    for x in squares:
        got, cycles, ovf = await run_sqrt(dut, x)
        ref = math.sqrt(x)
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        ok = re < 0.03 or ae < 0.02
        if not ok:
            fails += 1
        dut._log.info(
            f"  sqrt({x:5.1f}) = {got:.5f}  ref={ref:.5f}  "
            f"rel={re:.3%}  cycles={cycles}  {'ok' if ok else 'FAIL'}"
        )
    assert fails == 0, f"{fails} perfect-square cases failed"
    dut._log.info("PASS test_sqrt_perfect_squares")


@cocotb.test()
async def test_sqrt_sweep(dut):
    """General sweep across non-perfect-square values."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 60)
    dut._log.info("SQRT Q8.8 GENERAL SWEEP")
    dut._log.info("=" * 60)

    points = [0.1, 0.25, 0.5, 1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 50.0, 100.0]
    max_rel = 0.0
    fails = 0

    for x in points:
        got, cycles, ovf = await run_sqrt(dut, x)
        ref = math.sqrt(x)
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        ok = re < 0.03 or ae < 0.02
        if not ok:
            fails += 1
        if re > max_rel:
            max_rel = re
        dut._log.info(
            f"  sqrt({x:6.2f}) = {got:.5f}  ref={ref:.5f}  "
            f"rel={re:.3%}  abs={ae:.5f}  {'ok' if ok else 'FAIL'}"
        )

    dut._log.info(f"  Max relative error: {max_rel:.3%}")
    assert fails == 0, f"{fails} sweep points failed"
    dut._log.info("PASS test_sqrt_sweep")


@cocotb.test()
async def test_sqrt_identity(dut):
    """Identity check: sqrt(x)^2 ~= x (squared on host from chip output)."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("IDENTITY: sqrt(x)^2 ~= x")
    fails = 0
    for x in [2.0, 5.0, 10.0, 20.0, 50.0]:
        got, _, _ = await run_sqrt(dut, x)
        squared = got * got
        err = abs(squared - x)
        rel = err / max(abs(x), 1e-9)
        ok = rel < 0.06
        if not ok:
            fails += 1
        dut._log.info(
            f"  sqrt({x:.2f})={got:.5f}  squared={squared:.5f}  "
            f"err={err:.4f}  rel={rel:.3%}  {'ok' if ok else 'FAIL'}"
        )
    assert fails == 0, f"{fails} identity checks failed"
    dut._log.info("PASS test_sqrt_identity")


@cocotb.test()
async def test_sqrt_latency(dut):
    """Confirm the FSM takes exactly 4 cycles from start pulse to valid."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    _, cycles, _ = await run_sqrt(dut, 4.0)
    dut._log.info(f"Latency: {cycles} cycles after start pulse")
    assert cycles == 4, f"Expected 4-cycle latency, got {cycles}"
    dut._log.info("PASS test_sqrt_latency")


@cocotb.test()
async def test_sqrt_overflow_zero(dut):
    """x=0 -> ln(0) undefined -> ovf must be 1."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("OVERFLOW -- x=0 -> ovf must = 1")
    dut.x_in.value = 0
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    cycles = 0
    for _ in range(20):
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.valid.value) == 1:
            break
    ovf_val = int(dut.ovf.value)
    dut._log.info(f"  ovf={ovf_val}  out={q88_to_float(dut.result.value):.5f}")
    assert ovf_val == 1, f"ovf must be 1 when x=0, got {ovf_val}"
    dut._log.info("PASS test_sqrt_overflow_zero")
