"""
cocotb testbench for relu_int16 (synchronous, clk/rst/start/busy/valid)
Plain signed INT16 by default: WIDTH=16

Every test case logs its input alongside the got-vs-expected output so
a run's log is a full audit trail, not just a pass/fail.
"""
import random
import cocotb
from cocotb.clock import Clock

from int16_test_utils import tick, signed_n, wait_for_valid

CLK_PERIOD_NS = 10
WIDTH = 16
MAX_VAL = 32767
MIN_VAL = -32768


def signed16(v):
    return signed_n(v, WIDTH)


def sw_relu(x):
    return max(0, x)


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.din.value = 0
    await tick(dut)
    await tick(dut)
    await tick(dut)
    dut.rst.value = 0
    await tick(dut)


async def run_relu(dut, x):
    """Drive start, wait for valid, return the integer result."""
    dut.din.value = x & 0xFFFF
    dut.start.value = 1
    await tick(dut)  # edge that samples start; lands mid-cycle, settled
    assert dut.busy.value == 1, "busy should go high the cycle after start"
    dut.start.value = 0

    await wait_for_valid(dut)
    assert dut.busy.value == 0, "busy should be low once valid is asserted"

    return signed16(dut.dout.value.to_unsigned())


async def check_relu(dut, x):
    """Run one case, log input vs expected/got, and assert."""
    got = await run_relu(dut, x)
    expected = sw_relu(x)
    dut._log.info(f"  ReLU(din={x:>8})  got={got:>8}  expected={expected:>8}")
    assert got == expected, f"ReLU({x}) = {got}, expected {expected}"
    return got


@cocotb.test()
async def test_relu_basic_values(dut):
    """Directed test: known positive, negative, zero values"""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [1, -1, 5, -5, 0, MAX_VAL, MIN_VAL, 1, -1]
    for x in cases:
        await check_relu(dut, x)

    dut._log.info("Directed ReLU tests passed")


@cocotb.test()
async def test_relu_boundary_values(dut):
    """One LSB on either side of zero, and the extreme ends of the range."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [0, 1, -1, MAX_VAL, MAX_VAL - 1, MIN_VAL, MIN_VAL + 1, -2, 2]
    for x in cases:
        await check_relu(dut, x)

    dut._log.info("Boundary ReLU tests passed")


@cocotb.test()
async def test_relu_random(dut):
    """Randomized test across the full INT16 range, driven through start/valid"""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    random.seed(42)
    for _ in range(150):
        x = signed16(random.randint(-32768, 32767))
        await check_relu(dut, x)

    dut._log.info("150 random ReLU tests passed")


@cocotb.test()
async def test_relu_back_to_back(dut):
    """Fire a sequence of values back-to-back with no gaps beyond the
    required handshake, confirming no state leaks between calls."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    sequence = [5, -5, 0, MAX_VAL, MIN_VAL, -1, 1, -100, 100]
    for x in sequence:
        await check_relu(dut, x)

    dut._log.info("Back-to-back sequence test passed")


@cocotb.test()
async def test_relu_reset_midway(dut):
    """Assert rst while the FSM is busy and confirm it returns cleanly to IDLE"""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    dut.din.value = 5
    dut.start.value = 1
    await tick(dut)
    assert dut.busy.value == 1
    dut.start.value = 0

    # Reset mid-operation (while busy, before valid ever asserts)
    dut.rst.value = 1
    await tick(dut)
    dut.rst.value = 0
    await tick(dut)
    assert dut.busy.value == 0
    assert dut.valid.value == 0
    dut._log.info("  Mid-op reset: din=5 dropped, busy/valid both cleared as expected")

    # Block should work normally again afterward
    await check_relu(dut, 3)

    dut._log.info("Mid-operation reset test passed")
