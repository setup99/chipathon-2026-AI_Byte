# =============================================================================
#  test_wrapper_q88.py
#  Smoke test for eml_wrapper_q88 -- confirms each of the six opcodes
#  drives the correct underlying block and returns a sane result.
#  Not a full accuracy re-verification of each block (that already
#  exists in test_sigmoid_q88.py / test_tanh_q88.py / etc.) -- this
#  checks the WRAPPER's opcode routing and handshake forwarding.
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

OP_SIGMOID  = 0
OP_TANH     = 1
OP_RECIP    = 2
OP_SQRT     = 3
OP_SOFTMAX  = 4
OP_FEEDBACK = 5


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
    dut.opcode.value = 0
    dut.x_in.value = 0
    dut.z0_in.value = 0
    dut.z1_in.value = 0
    dut.z2_in.value = 0
    dut.z3_in.value = 0
    dut.x_ext.value = 0
    dut.y_ext.value = float_to_q88(1.0)
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def pulse_start(dut, timeout=60):
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    cycles = 0
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.valid.value) == 1:
            return cycles
    raise AssertionError("Timed out waiting for valid")


@cocotb.test()
async def test_wrapper_sigmoid(dut):
    """OP_SIGMOID routes to eml_sigmoid_q88 correctly."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_SIGMOID
    dut.x_in.value = float_to_q88(1.0)
    cycles = await pulse_start(dut)

    got = q88_to_float(dut.result.value)
    ref = 1.0 / (1.0 + math.exp(-1.0))
    dut._log.info(f"OP_SIGMOID  x=1.0  got={got:.5f}  ref={ref:.5f}  cycles={cycles}")
    assert cycles == 6, f"Expected 6 cycles for sigmoid, got {cycles}"
    assert abs(got - ref) < 0.05, f"Sigmoid result wrong: {got} vs {ref}"
    dut._log.info("PASS test_wrapper_sigmoid")


@cocotb.test()
async def test_wrapper_tanh(dut):
    """OP_TANH routes to eml_tanh_q88 correctly."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_TANH
    dut.x_in.value = float_to_q88(1.0)
    cycles = await pulse_start(dut)

    got = q88_to_float(dut.result.value)
    ref = math.tanh(1.0)
    dut._log.info(f"OP_TANH  x=1.0  got={got:.5f}  ref={ref:.5f}  cycles={cycles}")
    assert cycles == 7, f"Expected 7 cycles for tanh, got {cycles}"
    assert abs(got - ref) < 0.05, f"Tanh result wrong: {got} vs {ref}"
    dut._log.info("PASS test_wrapper_tanh")


@cocotb.test()
async def test_wrapper_recip(dut):
    """OP_RECIP routes to eml_recip_q88 correctly."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_RECIP
    dut.x_in.value = float_to_q88(2.0)
    cycles = await pulse_start(dut)

    got = q88_to_float(dut.result.value)
    ref = 1.0 / 2.0
    dut._log.info(f"OP_RECIP  x=2.0  got={got:.5f}  ref={ref:.5f}  cycles={cycles}")
    assert cycles == 4, f"Expected 4 cycles for recip, got {cycles}"
    assert abs(got - ref) < 0.05, f"Recip result wrong: {got} vs {ref}"
    dut._log.info("PASS test_wrapper_recip")


@cocotb.test()
async def test_wrapper_sqrt(dut):
    """OP_SQRT routes to eml_sqrt_q88 correctly."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_SQRT
    dut.x_in.value = float_to_q88(4.0)
    cycles = await pulse_start(dut)

    got = q88_to_float(dut.result.value)
    ref = math.sqrt(4.0)
    dut._log.info(f"OP_SQRT  x=4.0  got={got:.5f}  ref={ref:.5f}  cycles={cycles}")
    assert cycles == 4, f"Expected 4 cycles for sqrt, got {cycles}"
    assert abs(got - ref) < 0.05, f"Sqrt result wrong: {got} vs {ref}"
    dut._log.info("PASS test_wrapper_sqrt")


@cocotb.test()
async def test_wrapper_softmax(dut):
    """OP_SOFTMAX routes to eml_softmax_q88 and the 4-wide result bus works."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_SOFTMAX
    dut.z0_in.value = float_to_q88(1.0)
    dut.z1_in.value = float_to_q88(1.0)
    dut.z2_in.value = float_to_q88(1.0)
    dut.z3_in.value = float_to_q88(1.0)
    cycles = await pulse_start(dut)

    r0 = q88_to_float(dut.softmax_result0.value)
    r1 = q88_to_float(dut.softmax_result1.value)
    r2 = q88_to_float(dut.softmax_result2.value)
    r3 = q88_to_float(dut.softmax_result3.value)
    dut._log.info(
        f"OP_SOFTMAX  [1,1,1,1]  got=[{r0:.4f},{r1:.4f},{r2:.4f},{r3:.4f}]  "
        f"cycles={cycles}  (expect all ~0.25)"
    )
    assert cycles == 35, f"Expected 35 cycles for softmax, got {cycles}"
    for r in (r0, r1, r2, r3):
        assert abs(r - 0.25) < 0.05, f"Softmax element wrong: {r} vs 0.25"
    # also confirm the single-value result port stays inert for this opcode
    assert int(dut.result.value) == 0, "result port should be 0 during OP_SOFTMAX"
    dut._log.info("PASS test_wrapper_softmax")


@cocotb.test()
async def test_wrapper_feedback(dut):
    """OP_FEEDBACK routes to eml_feedback_cell_q88 correctly (feed-forward mode)."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_FEEDBACK
    dut.x_ext.value = float_to_q88(0.0)
    dut.y_ext.value = float_to_q88(1.0)
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    cycles = await pulse_start(dut)

    got = q88_to_float(dut.result.value)
    dut._log.info(f"OP_FEEDBACK  eml(0,1)  got={got:.5f}  cycles={cycles}  (expect 1.0)")
    assert abs(got - 1.0) < 0.01, f"Feedback result wrong: {got} vs 1.0"
    dut._log.info("PASS test_wrapper_feedback")


@cocotb.test()
async def test_wrapper_opcode_switching(dut):
    """
    Switch opcodes back-to-back (sigmoid -> sqrt -> tanh) and confirm
    each call returns the CORRECT block's result -- this is the actual
    point of the wrapper: that switching opcode doesn't leak state or
    drive the wrong block's start line.
    """
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_SIGMOID
    dut.x_in.value = float_to_q88(0.0)
    await pulse_start(dut)
    got_sig = q88_to_float(dut.result.value)
    dut._log.info(f"1) OP_SIGMOID x=0  got={got_sig:.5f}  (expect ~0.5)")
    assert abs(got_sig - 0.5) < 0.01

    dut.opcode.value = OP_SQRT
    dut.x_in.value = float_to_q88(9.0)
    await pulse_start(dut)
    got_sqrt = q88_to_float(dut.result.value)
    dut._log.info(f"2) OP_SQRT x=9  got={got_sqrt:.5f}  (expect ~3.0)")
    assert abs(got_sqrt - 3.0) < 0.05

    dut.opcode.value = OP_TANH
    dut.x_in.value = float_to_q88(0.0)
    await pulse_start(dut)
    got_tanh = q88_to_float(dut.result.value)
    dut._log.info(f"3) OP_TANH x=0  got={got_tanh:.5f}  (expect 0.0)")
    assert abs(got_tanh - 0.0) < 0.01

    dut._log.info("PASS test_wrapper_opcode_switching")
