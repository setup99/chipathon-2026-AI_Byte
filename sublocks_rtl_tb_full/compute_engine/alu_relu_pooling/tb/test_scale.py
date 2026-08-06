"""
cocotb testbench for scale_int16_to_int8 (synchronous, clk/rst/start/busy/valid)
Default: WIDTH_IN=16, WIDTH_OUT=8, SHIFT=8
  -> converts a plain INT16 accumulator down to a plain signed INT8.

Every test case logs its input alongside the got-vs-expected output
(and overflow flag) so a run's log is a full audit trail, not just a
pass/fail.
"""
import random
import cocotb
from cocotb.clock import Clock

from int16_test_utils import tick, wait_for_valid

CLK_PERIOD_NS = 10
WIDTH_IN = 16
WIDTH_OUT = 8
SHIFT = 8

IN_MAX = (1 << (WIDTH_IN - 1)) - 1
IN_MIN = -(1 << (WIDTH_IN - 1))
OUT_MAX = (1 << (WIDTH_OUT - 1)) - 1
OUT_MIN = -(1 << (WIDTH_OUT - 1))


def signed_in(v):
    v &= (1 << WIDTH_IN) - 1
    if v & (1 << (WIDTH_IN - 1)):
        v -= (1 << WIDTH_IN)
    return v


def signed_out(v):
    v &= (1 << WIDTH_OUT) - 1
    if v & (1 << (WIDTH_OUT - 1)):
        v -= (1 << WIDTH_OUT)
    return v


def sw_scale(din_raw):
    """Model: arithmetic right-shift by SHIFT, then saturate to WIDTH_OUT."""
    shifted = din_raw >> SHIFT  # Python's >> on ints is arithmetic (floor)
    overflow = 0
    if shifted > OUT_MAX:
        shifted, overflow = OUT_MAX, 1
    elif shifted < OUT_MIN:
        shifted, overflow = OUT_MIN, 1
    return shifted, overflow


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.din.value = 0
    await tick(dut)
    await tick(dut)
    await tick(dut)
    dut.rst.value = 0
    await tick(dut)


async def run_scale(dut, din_raw):
    dut.din.value = din_raw & ((1 << WIDTH_IN) - 1)
    dut.start.value = 1
    await tick(dut)
    assert dut.busy.value == 1, "busy should go high the cycle after start"
    dut.start.value = 0

    await wait_for_valid(dut)
    assert dut.busy.value == 0

    dout = signed_out(dut.dout.value.to_unsigned())
    overflow = int(dut.overflow.value)
    return dout, overflow


async def check_scale(dut, din_raw):
    """Run one case, log input vs expected/got, and assert."""
    got, ovf = await run_scale(dut, din_raw)
    exp, exp_ovf = sw_scale(din_raw)
    dut._log.info(
        f"  scale(din={din_raw:>7})  got={got:>5} (ovf={ovf})  "
        f"expected={exp:>5} (ovf={exp_ovf})"
    )
    assert got == exp, f"scale({din_raw}) = {got}, expected {exp}"
    assert ovf == exp_ovf, f"scale({din_raw}) overflow={ovf}, expected {exp_ovf}"
    return got, ovf


@cocotb.test()
async def test_scale_directed(dut):
    """Known INT16 values -> expected plain INT8 after shift+saturate"""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        0,
        256,          # -> 1
        -256,         # -> -1
        127 * 256,    # exactly at max -> 127
        -128 * 256,   # exactly at min -> -128
        200,          # truncates to 0 (arithmetic shift floors)
        -200,         # floors toward -1, not 0
        32767,        # max possible 16-bit value -> exactly 127, no overflow
        -32768,       # min possible 16-bit value -> exactly -128, no overflow
        1,            # smallest positive input -> 0
        -1,           # smallest-magnitude negative input -> floors to -1
    ]
    # Note: with the default WIDTH_IN=16, WIDTH_OUT=8, SHIFT=8, overflow is
    # mathematically unreachable -- shifting any 16-bit signed value right
    # by 8 bits always lands exactly inside the 8-bit signed range. The
    # saturation logic is still real defensive hardware (needed the moment
    # SHIFT is reconfigured to less than WIDTH_IN-WIDTH_OUT); see
    # test_saturation.py for a build that actually exercises it.
    for din_raw in cases:
        await check_scale(dut, din_raw)

    dut._log.info("Directed scale tests passed")


@cocotb.test()
async def test_scale_random(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    random.seed(11)
    for _ in range(150):
        din_raw = signed_in(random.randint(IN_MIN, IN_MAX))
        await check_scale(dut, din_raw)

    dut._log.info("150 random scale tests passed")
