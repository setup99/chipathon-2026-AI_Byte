"""
cocotb testbench for scale_int16_to_int8 built with SHIFT=4 (overridden via
Makefile -P flag) so that overflow is actually reachable and the
saturate/overflow branch gets genuinely exercised, not just proven
unreachable by construction (as it is with the default SHIFT=8 build).

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
SHIFT = 4  # must match the Makefile's -P override

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
    shifted = din_raw >> SHIFT
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
    assert dut.busy.value == 1
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
async def test_saturation_actually_triggers(dut):
    """With SHIFT=4, values whose integer part exceeds int8 range must saturate."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        2000,     # 2000>>4=125, within range, no overflow
        2032,     # 2032>>4=127, exactly at max
        2048,     # 2048>>4=128, overflow -> saturate to 127
        32767,    # max int16 -> way past int8 max, must saturate
        -2048,    # -2048>>4=-128, exactly at min
        -2064,    # -2064>>4=-129, overflow -> saturate to -128
        -32768,   # min int16 -> way past int8 min, must saturate
    ]
    for din_raw in cases:
        await check_scale(dut, din_raw)

    dut._log.info("Saturation-reachable directed tests passed")


@cocotb.test()
async def test_saturation_boundary_sweep(dut):
    """Sweep one LSB on either side of the exact saturation boundary in
    both directions."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    boundary_hi = OUT_MAX << SHIFT       # last value that still fits (127<<4=2032)
    boundary_lo = OUT_MIN << SHIFT       # last value that still fits (-128<<4=-2048)
    cases = [
        boundary_hi,          # exactly at max, no overflow
        boundary_hi + 1,      # one past max, overflow
        boundary_lo,          # exactly at min, no overflow
        boundary_lo - 1,      # one past min, overflow
    ]
    for din_raw in cases:
        await check_scale(dut, din_raw)

    dut._log.info("Saturation boundary sweep passed")


@cocotb.test()
async def test_saturation_random(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    random.seed(99)
    saw_overflow = False
    for _ in range(200):
        din_raw = signed_in(random.randint(IN_MIN, IN_MAX))
        _, ovf = await check_scale(dut, din_raw)
        saw_overflow = saw_overflow or ovf

    assert saw_overflow, "Randomized sweep should have hit overflow at least once with SHIFT=4"
    dut._log.info("200 random tests passed, including real overflow cases")
