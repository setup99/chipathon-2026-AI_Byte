# =============================================================================
#  test_tanh_q88.py
#  cocotb testbench for eml_tanh_q88 (tanh(x), Q8.8, 7-state FSM)
#
#  Same structure as test_sigmoid_q88.py -- tanh is sigmoid's chain with
#  input doubling and an output rescale, so the test discipline carries
#  over directly: sweep, basic exact-zero case, identity check, latency,
#  back-to-back calls.
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


async def run_tanh(dut, x: float, timeout=20):
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


def true_tanh(x: float) -> float:
    return math.tanh(x)


@cocotb.test()
async def test_tanh_basic(dut):
    """tanh(0) = 0 exactly -- e^0=1 is exact, 1-ln(2)... let's just check
    it lands very close to zero given the chain's exactness at x=0."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    got, cycles, ovf = await run_tanh(dut, 0.0)
    dut._log.info(f"tanh(0) = {got:.6f}  (cycles={cycles}, ovf={ovf})")
    assert abs(got - 0.0) < 1e-3, f"tanh(0) should be ~0.0, got {got}"
    assert ovf == 0
    dut._log.info("PASS test_tanh_basic")


@cocotb.test()
async def test_tanh_sweep(dut):
    """Sweep tanh(x) across a range -- note: tanh sees 2x internally via
    the eml tile (input is doubled before the EML chain), so the
    saturation/error behaviour kicks in at roughly half the |x| that
    sigmoid shows it at. Range chosen accordingly: [-2, +2] instead of
    sigmoid's [-4, +4]."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 64)
    dut._log.info("TANH Q8.8 SWEEP")
    dut._log.info("=" * 64)

    points = [-2.0, -1.5, -1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0, 1.5, 2.0]
    max_rel = 0.0
    fails = 0

    for x in points:
        got, cycles, ovf = await run_tanh(dut, x)
        ref = true_tanh(x)
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        # Near x=0, true tanh(x) is small, so relative error explodes the
        # same way sigmoid's did near its tails -- use an absolute floor
        # there, same pattern as the sigmoid extreme-input fix.
        if abs(x) <= 0.25:
            ok = ae < 0.02
        else:
            ok = re < 0.06 or ae < 0.03
        if not ok:
            fails += 1
        if re > max_rel and abs(x) > 0.25:
            max_rel = re
        dut._log.info(
            f"  tanh({x:+5.2f}) = {got:.5f}  ref={ref:.5f}  "
            f"rel={re:.3%}  abs={ae:.5f}  cycles={cycles}  {'ok' if ok else 'FAIL'}"
        )

    dut._log.info(f"  Max relative error (|x|>0.25): {max_rel:.3%}")
    assert fails == 0, f"{fails} sweep points failed"
    dut._log.info("PASS test_tanh_sweep")


@cocotb.test()
async def test_tanh_symmetry(dut):
    """Identity check: tanh(-x) = -tanh(x) for all x (odd function)."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("SYMMETRY: tanh(-x) = -tanh(x)")
    fails = 0
    for x in [0.25, 0.5, 1.0, 1.5, 2.0]:
        pos, _, _ = await run_tanh(dut, x)
        neg, _, _ = await run_tanh(dut, -x)
        total = pos + neg
        err = abs(total - 0.0)
        ok = err < 0.05
        if not ok:
            fails += 1
        dut._log.info(
            f"  tanh({x:+.2f})+tanh({-x:+.2f}) = {pos:.5f}+{neg:.5f} "
            f"= {total:.5f}  err={err:.4f}  {'ok' if ok else 'FAIL'}"
        )
    assert fails == 0, f"{fails} symmetry checks failed"
    dut._log.info("PASS test_tanh_symmetry")


@cocotb.test()
async def test_tanh_vs_sigmoid_identity(dut):
    """
    Cross-check identity: tanh(x) = 2*sigma(2x) - 1 should hold against
    the true (non-approximated) sigmoid -- this directly verifies the
    derivation used to build the FSM, not just the FSM's self-consistency.
    """
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("IDENTITY: tanh(x) vs 2*sigma(2x)-1 (true math, not hardware sigma)")
    fails = 0
    for x in [0.5, 1.0, 1.5]:
        got, _, _ = await run_tanh(dut, x)
        true_sigma_2x = 1.0 / (1.0 + math.exp(-2.0 * x))
        expected = 2.0 * true_sigma_2x - 1.0
        ae = abs(got - expected)
        ok = ae < 0.04
        if not ok:
            fails += 1
        dut._log.info(
            f"  tanh({x:.2f})={got:.5f}  2*sigma(2*{x:.2f})-1={expected:.5f}  "
            f"err={ae:.4f}  {'ok' if ok else 'FAIL'}"
        )
    assert fails == 0, f"{fails} identity checks failed"
    dut._log.info("PASS test_tanh_vs_sigmoid_identity")


@cocotb.test()
async def test_tanh_latency(dut):
    """Confirm the FSM takes exactly 7 cycles from start pulse to valid
    (one more than sigmoid's 6, for the extra rescale step)."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    _, cycles, _ = await run_tanh(dut, 1.0)
    dut._log.info(f"Latency: {cycles} cycles after start pulse")
    assert cycles == 7, f"Expected 7-cycle latency, got {cycles}"
    dut._log.info("PASS test_tanh_latency")


@cocotb.test()
async def test_tanh_back_to_back(dut):
    """Issue several tanh calls in sequence without resetting between them."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("BACK-TO-BACK calls (no reset between)")
    test_vals = [0.0, 1.0, -1.0, 0.5, -0.5]
    fails = 0
    for x in test_vals:
        got, cycles, ovf = await run_tanh(dut, x)
        ref = true_tanh(x)
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        ok = re < 0.06 or ae < 0.03
        if not ok:
            fails += 1
        dut._log.info(f"  tanh({x:+.2f}) = {got:.4f}  ref={ref:.4f}  rel={re:.3%}")
    assert fails == 0, f"{fails} back-to-back calls failed"
    dut._log.info("PASS test_tanh_back_to_back")
