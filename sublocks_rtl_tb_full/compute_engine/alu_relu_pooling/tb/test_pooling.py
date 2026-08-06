"""
cocotb testbench for pool_int16 (synchronous, clk/rst/start/busy/valid)
Unified module: opcode 0 = MAX pooling, opcode 1 = AVERAGE pooling
Plain signed INT16 by default: WIDTH=16

Every test case logs its four inputs alongside the got-vs-expected
output so a run's log is a full audit trail, not just a pass/fail.
"""
import random
import cocotb
from cocotb.clock import Clock

from int16_test_utils import tick, signed_n, wait_for_valid

CLK_PERIOD_NS = 10
WIDTH = 16
MAX_VAL = 32767
MIN_VAL = -32768

POOL_MAX = 0
POOL_AVG = 1
POOL_NAMES = {POOL_MAX: "MAX", POOL_AVG: "AVG"}


def signed16(v):
    return signed_n(v, WIDTH)


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.A.value = 0
    dut.B.value = 0
    dut.C.value = 0
    dut.D.value = 0
    dut.opcode.value = 0
    await tick(dut)
    await tick(dut)
    await tick(dut)
    dut.rst.value = 0
    await tick(dut)


async def run_pool(dut, a, b, c, d, opcode):
    dut.A.value = a & 0xFFFF
    dut.B.value = b & 0xFFFF
    dut.C.value = c & 0xFFFF
    dut.D.value = d & 0xFFFF
    dut.opcode.value = opcode
    dut.start.value = 1
    await tick(dut)
    assert dut.busy.value == 1, "busy should go high the cycle after start"
    dut.start.value = 0

    await wait_for_valid(dut)
    assert dut.busy.value == 0

    return signed16(dut.out.value.to_unsigned())


def sw_pool(vals, opcode):
    if opcode == POOL_MAX:
        return max(vals)
    return sum(vals) >> 2  # arithmetic (floor) shift, matches hardware


async def check_pool(dut, vals, opcode):
    """Run one case, log inputs vs expected/got, and assert."""
    a, b, c, d = vals
    got = await run_pool(dut, a, b, c, d, opcode)
    expected = sw_pool(vals, opcode)
    op = POOL_NAMES.get(opcode, f"op{opcode}")
    dut._log.info(
        f"  {op:<3} A={a:>7} B={b:>7} C={c:>7} D={d:>7}  "
        f"got={got:>8}  expected={expected:>8}"
    )
    assert got == expected, f"{op}({vals}) = {got}, expected {expected}"
    return got


# ---------------- MAX POOL ----------------

@cocotb.test()
async def test_max_pool_directed(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (1, 2, 0, -1),
        (-1, -2, 0, -3),
        (0, 0, 0, 0),
        (127, -128, 0, 63),
        (MAX_VAL, MIN_VAL, 0, 0),
        (MIN_VAL, MIN_VAL, MIN_VAL, MIN_VAL),
    ]
    for vals in cases:
        await check_pool(dut, vals, POOL_MAX)

    dut._log.info("Directed max-pool tests passed")


@cocotb.test()
async def test_max_pool_ties(dut):
    """All values equal, and repeated ties between pairs -- confirms the
    comparator tree doesn't silently favor the wrong operand on a tie."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (5, 5, 5, 5),
        (5, 5, -5, -5),
        (-5, -5, -5, -5),
        (0, 0, 5, 5),
    ]
    for vals in cases:
        await check_pool(dut, vals, POOL_MAX)

    dut._log.info("Max-pool tie tests passed")


@cocotb.test()
async def test_max_pool_random(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    random.seed(1)
    for _ in range(100):
        vals = tuple(signed16(random.randint(-32768, 32767)) for _ in range(4))
        await check_pool(dut, vals, POOL_MAX)

    dut._log.info("100 random max-pool tests passed")


# ---------------- AVERAGE POOL ----------------

@cocotb.test()
async def test_avg_pool_directed(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (1, 2, 0, -1),
        (0, 0, 0, 0),
        (-4, -4, -4, -4),
        (100, -100, 50, -50),
        (MAX_VAL, MAX_VAL, MAX_VAL, MAX_VAL),
        (MIN_VAL, MIN_VAL, MIN_VAL, MIN_VAL),
    ]
    for vals in cases:
        await check_pool(dut, vals, POOL_AVG)

    dut._log.info("Directed avg-pool tests passed")


@cocotb.test()
async def test_avg_pool_negative_rounding(dut):
    """Average pooling uses an arithmetic (floor) shift to divide by 4,
    so sums that aren't exact multiples of 4 round toward negative
    infinity, not toward zero -- confirm that explicitly for negatives."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (-1, 0, 0, 0),   # sum=-1 -> -1>>2 = -1 (floor), not 0
        (-1, -1, -1, 0),  # sum=-3 -> -3>>2 = -1 (floor), not 0
        (1, 1, 1, 0),    # sum=3  -> 3>>2  = 0
        (-5, -1, -1, -1),  # sum=-8 -> -2 exactly
    ]
    for vals in cases:
        await check_pool(dut, vals, POOL_AVG)

    dut._log.info("Avg-pool negative-rounding tests passed")


@cocotb.test()
async def test_avg_pool_random(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    random.seed(2)
    for _ in range(100):
        vals = tuple(signed16(random.randint(-16384, 16383)) for _ in range(4))
        await check_pool(dut, vals, POOL_AVG)

    dut._log.info("100 random avg-pool tests passed")


@cocotb.test()
async def test_opcode_switching(dut):
    """Same operands, different opcode each call -> confirms opcode is
    correctly latched per-operation and doesn't leak between calls."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    vals = (4, 2, 1, -1)
    await check_pool(dut, vals, POOL_MAX)
    await check_pool(dut, vals, POOL_AVG)
    await check_pool(dut, vals, POOL_MAX)
    await check_pool(dut, vals, POOL_AVG)

    dut._log.info("Opcode switching test passed")
