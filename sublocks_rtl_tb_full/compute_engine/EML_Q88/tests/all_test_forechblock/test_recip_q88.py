# =============================================================================
#  test_recip_q88.py
#  cocotb testbench for eml_recip_q88 (1/x, Q8.8, 2-pass FSM)
#
#  Same encode/decode and assertion discipline as the other Q8.8 suites
#  built earlier (sigmoid, softmax): tolerances derived from the actual
#  measured error, not guessed.
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


async def run_recip(dut, x: float, timeout=20):
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
async def test_recip_basic(dut):
    """1/1.0 = 1.0 exactly -- ln(1)=0 is exact in Mitchell, exp(0)=1 is exact."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    got, cycles, ovf = await run_recip(dut, 1.0)
    dut._log.info(f"1/1.0 = {got:.6f}  (cycles={cycles}, ovf={ovf})")
    assert abs(got - 1.0) < 1e-3, f"1/1.0 should be ~1.0, got {got}"
    assert ovf == 0
    dut._log.info("PASS test_recip_basic")


@cocotb.test()
async def test_recip_sweep(dut):
    """Sweep 1/x across a range of positive values."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 60)
    dut._log.info("RECIPROCAL Q8.8 SWEEP")
    dut._log.info("=" * 60)

    points = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0, 16.0, 32.0, 64.0]
    max_rel = 0.0
    fails = 0

    for x in points:
        got, cycles, ovf = await run_recip(dut, x)
        ref = 1.0 / x
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        # Two-pass identity -> error compounds through one ln() and one
        # exp(), same mechanism as half of the sigmoid chain. Bound set
        # from the Mitchell correction budget (0.39%-0.81% per stage)
        # plus Q8.8 quantisation, with margin -- not copied from sigmoid's
        # bound since this is a shorter chain (2 passes, not 3) and should
        # do somewhat better.
        ok = re < 0.04 or ae < 0.02
        if not ok:
            fails += 1
        if re > max_rel:
            max_rel = re
        dut._log.info(
            f"  1/{x:<6.3f} = {got:.5f}  ref={ref:.5f}  "
            f"rel={re:.3%}  abs={ae:.5f}  cycles={cycles}  {'ok' if ok else 'FAIL'}"
        )

    dut._log.info(f"  Max relative error: {max_rel:.3%}")
    assert fails == 0, f"{fails} sweep points failed"
    dut._log.info("PASS test_recip_sweep")


@cocotb.test()
async def test_recip_identity(dut):
    """Identity check: x * (1/x) should be ~1.0 (computed on host from chip output)."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("IDENTITY: x * recip(x) ~= 1.0")
    fails = 0
    for x in [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]:
        got, _, _ = await run_recip(dut, x)
        product = x * got
        err = abs(product - 1.0)
        ok = err < 0.04
        if not ok:
            fails += 1
        dut._log.info(
            f"  {x:.2f} * recip({x:.2f})={got:.5f}  = {product:.5f}  "
            f"err={err:.4f}  {'ok' if ok else 'FAIL'}"
        )
    assert fails == 0, f"{fails} identity checks failed"
    dut._log.info("PASS test_recip_identity")


@cocotb.test()
async def test_recip_latency(dut):
    """Confirm the FSM takes exactly 4 cycles from start pulse to valid."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    _, cycles, _ = await run_recip(dut, 2.0)
    dut._log.info(f"Latency: {cycles} cycles after start pulse")
    assert cycles == 4, f"Expected 4-cycle latency, got {cycles}"
    dut._log.info("PASS test_recip_latency")


@cocotb.test()
async def test_recip_overflow_zero(dut):
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
    dut._log.info("PASS test_recip_overflow_zero")


@cocotb.test()
async def test_recip_back_to_back(dut):
    """Several consecutive calls with no reset between them."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("BACK-TO-BACK calls (no reset between)")
    test_vals = [1.0, 2.0, 0.5, 4.0, 0.25]
    fails = 0
    for x in test_vals:
        got, cycles, ovf = await run_recip(dut, x)
        ref = 1.0 / x
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        ok = re < 0.04 or ae < 0.02
        if not ok:
            fails += 1
        dut._log.info(f"  1/{x:.2f} = {got:.5f}  ref={ref:.5f}  rel={re:.3%}")
    assert fails == 0, f"{fails} back-to-back calls failed"
    dut._log.info("PASS test_recip_back_to_back")
