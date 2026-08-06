"""
cocotb testbench for alu_int16 (synchronous, clk/rst/start/busy/valid)
Plain signed INT16 by default: WIDTH=16

Every test case below logs its inputs alongside the got-vs-expected
result (and overflow flag) so a run's log is a full audit trail, not
just a pass/fail.
"""
import random
import cocotb
from cocotb.clock import Clock

from int16_test_utils import tick, signed_n, wait_for_valid

CLK_PERIOD_NS = 10
WIDTH = 16

MAX_VAL = 32767
MIN_VAL = -32768

OP_ADD = 0
OP_SUB = 1
OP_MUL = 2
OP_NAMES = {OP_ADD: "ADD", OP_SUB: "SUB", OP_MUL: "MUL"}


def signed16(v):
    return signed_n(v, WIDTH)


def sw_alu(a_raw, b_raw, opcode):
    """Model the exact integer + saturation behavior of the RTL."""
    if opcode == OP_ADD:
        raw = a_raw + b_raw
    elif opcode == OP_SUB:
        raw = a_raw - b_raw
    elif opcode == OP_MUL:
        raw = a_raw * b_raw  # full-precision product, no rescale
    else:
        raw = 0

    overflow = 0
    if raw > MAX_VAL:
        raw, overflow = MAX_VAL, 1
    elif raw < MIN_VAL:
        raw, overflow = MIN_VAL, 1
    return raw, overflow


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.A.value = 0
    dut.B.value = 0
    dut.opcode.value = 0
    await tick(dut)
    await tick(dut)
    await tick(dut)
    dut.rst.value = 0
    await tick(dut)


async def run_alu(dut, a_raw, b_raw, opcode):
    dut.A.value = a_raw & 0xFFFF
    dut.B.value = b_raw & 0xFFFF
    dut.opcode.value = opcode
    dut.start.value = 1
    await tick(dut)
    assert dut.busy.value == 1, "busy should go high the cycle after start"
    dut.start.value = 0

    await wait_for_valid(dut)
    assert dut.busy.value == 0

    result = signed16(dut.result.value.to_unsigned())
    overflow = int(dut.overflow.value)
    return result, overflow


def log_case(dut, a, b, opcode, got, exp, got_ovf, exp_ovf):
    op = OP_NAMES.get(opcode, f"op{opcode}")
    dut._log.info(
        f"  {op:<3} A={a:>7} B={b:>7}  "
        f"got={got:>7} (ovf={got_ovf})  expected={exp:>7} (ovf={exp_ovf})"
    )


async def check_alu(dut, a, b, opcode):
    """Run one case, log inputs vs expected/got, and assert."""
    got, ovf = await run_alu(dut, a, b, opcode)
    exp, exp_ovf = sw_alu(a, b, opcode)
    log_case(dut, a, b, opcode, got, exp, ovf, exp_ovf)
    assert got == exp, f"{OP_NAMES.get(opcode)} A={a} B={b}: got={got} expected={exp}"
    assert ovf == exp_ovf, \
        f"{OP_NAMES.get(opcode)} A={a} B={b}: overflow got={ovf} expected={exp_ovf}"
    return got, ovf


@cocotb.test()
async def test_alu_add_directed(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    for a, b in [(1, 2), (-1, 1), (0, 0), (100, 27), (-100, -27), (32767, 0), (-32768, 0)]:
        await check_alu(dut, a, b, OP_ADD)

    dut._log.info("Directed ADD tests passed")


@cocotb.test()
async def test_alu_add_saturation_boundary(dut):
    """Exercise the exact +/- saturation boundary for ADD, one LSB on
    each side of the edge."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (32766, 1),        # exactly MAX_VAL, no overflow
        (32767, 1),        # one past MAX_VAL, overflow
        (32767, 32767),    # deep overflow
        (-32767, -1),      # exactly MIN_VAL, no overflow
        (-32768, -1),      # one past MIN_VAL, overflow
        (-32768, -32768),  # deep underflow
    ]
    for a, b in cases:
        await check_alu(dut, a, b, OP_ADD)

    dut._log.info("ADD saturation boundary tests passed")


@cocotb.test()
async def test_alu_sub_directed(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    for a, b in [(1, 2), (-1, -1), (0, 5), (50, -50), (32767, -1), (-32768, 1)]:
        await check_alu(dut, a, b, OP_SUB)

    dut._log.info("Directed SUB tests passed")


@cocotb.test()
async def test_alu_sub_saturation_boundary(dut):
    """Exercise the exact +/- saturation boundary for SUB."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (32767, 0),        # exactly MAX_VAL, no overflow
        (32767, -1),       # one past MAX_VAL, overflow
        (-32768, 0),       # exactly MIN_VAL, no overflow
        (-32768, 1),       # one past MIN_VAL, overflow
        (32767, -32768),   # deep overflow
        (-32768, 32767),   # deep underflow
    ]
    for a, b in cases:
        await check_alu(dut, a, b, OP_SUB)

    dut._log.info("SUB saturation boundary tests passed")


@cocotb.test()
async def test_alu_mul_directed(dut):
    """Confirms plain integer multiply (no rescale), non-saturating cases."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (3, 2), (2, 2), (-1, 3), (5, 5),
        (0, 12345), (-1, -1), (1, -1), (1, 1),
    ]
    for a, b in cases:
        await check_alu(dut, a, b, OP_MUL)

    dut._log.info("Directed MUL tests passed")


@cocotb.test()
async def test_alu_mul_saturation(dut):
    """Force overflow cases in both directions: large * large should
    saturate, not wrap."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (20000, 20000),    # positive * positive overflow -> MAX_VAL
        (-20000, 20000),   # negative * positive overflow -> MIN_VAL
        (-20000, -20000),  # negative * negative overflow -> MAX_VAL
        (32767, 32767),    # extreme positive overflow
        (-32768, -32768),  # extreme negative-times-negative overflow
        (-32768, 32767),   # extreme negative-times-positive overflow
    ]
    for a, b in cases:
        await check_alu(dut, a, b, OP_MUL)

    dut._log.info("Multiply saturation tests passed")


@cocotb.test()
async def test_alu_random(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    random.seed(7)
    ops = [OP_ADD, OP_SUB, OP_MUL]
    for _ in range(200):
        a_raw = signed16(random.randint(-32768, 32767))
        b_raw = signed16(random.randint(-32768, 32767))
        opcode = random.choice(ops)
        await check_alu(dut, a_raw, b_raw, opcode)

    dut._log.info("200 random ALU tests passed (add/sub/mul + saturation)")


@cocotb.test()
async def test_alu_busy_blocks_new_start(dut):
    """While busy, driving start should not restart the operation with
    stale/new operands until the FSM returns to IDLE."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    a_raw, b_raw = 1, 1
    dut.A.value = a_raw & 0xFFFF
    dut.B.value = b_raw & 0xFFFF
    dut.opcode.value = OP_ADD
    dut.start.value = 1
    await tick(dut)
    assert dut.busy.value == 1
    dut.start.value = 0

    # Try to sneak in a start + different operand while busy
    stale_a = 50
    dut.A.value = stale_a & 0xFFFF
    dut.start.value = 1
    await tick(dut)
    dut.start.value = 0

    await wait_for_valid(dut)

    result = signed16(dut.result.value.to_unsigned())
    expected = 2  # ORIGINAL 1 + 1, not stale_a + 1
    dut._log.info(
        f"  ADD A={a_raw} B={b_raw} (sneaked A={stale_a} while busy)  "
        f"got={result}  expected={expected}"
    )
    assert result == expected, \
        f"FSM should ignore start while busy; got {result}, expected {expected}"

    dut._log.info("Busy-blocks-new-start test passed")


@cocotb.test()
async def test_alu_back_to_back_ops(dut):
    """Fire a sequence of different ops back-to-back with no gaps beyond
    the required handshake, confirming no state leaks between calls."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    sequence = [
        (10, 5, OP_ADD),
        (10, 5, OP_SUB),
        (10, 5, OP_MUL),
        (-10, 5, OP_MUL),
        (32767, 32767, OP_ADD),
        (0, 0, OP_MUL),
    ]
    for a, b, opcode in sequence:
        await check_alu(dut, a, b, opcode)

    dut._log.info("Back-to-back mixed-opcode sequence test passed")
