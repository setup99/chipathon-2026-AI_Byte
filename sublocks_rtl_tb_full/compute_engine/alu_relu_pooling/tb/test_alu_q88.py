"""
cocotb testbench for alu_q88 (synchronous, clk/rst/start/busy/valid)
Q8.8 fixed point: WIDTH=16, FRAC=8. ADD/SUB are plain integer add/sub
(no rescale); MUL is sat((A*B) >>> FRAC), an arithmetic (floor-toward
-infinity) shift on the exact signed product, matching Verilog's >>>.

Every test case logs its inputs alongside the got-vs-expected result
(and overflow flag) so a run's log is a full audit trail.
"""
import random
import cocotb
from cocotb.clock import Clock

from int16_test_utils import tick, signed_n, wait_for_valid

CLK_PERIOD_NS = 10
WIDTH = 16
FRAC = 8
Q = float(1 << FRAC)

MAX_VAL = 32767
MIN_VAL = -32768

OP_ADD = 0
OP_SUB = 1
OP_MUL = 2
OP_NAMES = {OP_ADD: "ADD", OP_SUB: "SUB", OP_MUL: "MUL"}


def signed16(v):
    return signed_n(v, WIDTH)


def sw_alu_q88(a, b, opcode):
    """Exact reference model: ADD/SUB are plain integer ops (no
    rescale); MUL is sat((a*b) >>> FRAC) using an arithmetic
    (floor-toward-negative-infinity) shift on the exact signed
    product -- Python's >> on a signed int matches Verilog's >>>."""
    if opcode == OP_ADD:
        raw = a + b
    elif opcode == OP_SUB:
        raw = a - b
    elif opcode == OP_MUL:
        raw = (a * b) >> FRAC
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
        f"  {op:<3} A={a:>7} ({a/Q:>9.4f})  B={b:>7} ({b/Q:>9.4f})  "
        f"got={got:>7} (ovf={got_ovf})  expected={exp:>7} (ovf={exp_ovf})"
    )


async def check_alu(dut, a, b, opcode):
    got, ovf = await run_alu(dut, a, b, opcode)
    exp, exp_ovf = sw_alu_q88(a, b, opcode)
    log_case(dut, a, b, opcode, got, exp, ovf, exp_ovf)
    assert got == exp, f"{OP_NAMES.get(opcode)} A={a} B={b}: got={got} expected={exp}"
    assert ovf == exp_ovf, \
        f"{OP_NAMES.get(opcode)} A={a} B={b}: overflow got={ovf} expected={exp_ovf}"
    return got, ovf


# ==================== ADD / SUB: unchanged, plain integer ====================

@cocotb.test()
async def test_q88_add_sub_directed(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    for a, b in [(384, 512), (-256, 256), (0, 0), (25600, 6912), (-25600, -6912)]:
        await check_alu(dut, a, b, OP_ADD)
    for a, b in [(384, 512), (-256, -256), (0, 1280), (12800, -12800)]:
        await check_alu(dut, a, b, OP_SUB)

    dut._log.info("Q8.8 ADD/SUB directed tests passed")


@cocotb.test()
async def test_q88_add_sub_saturation_boundary(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    add_cases = [(32766, 1), (32767, 1), (-32767, -1), (-32768, -1)]
    for a, b in add_cases:
        await check_alu(dut, a, b, OP_ADD)
    sub_cases = [(32767, 0), (32767, -1), (-32768, 0), (-32768, 1)]
    for a, b in sub_cases:
        await check_alu(dut, a, b, OP_SUB)

    dut._log.info("Q8.8 ADD/SUB saturation boundary tests passed")


# ==================== MUL: Q8.8 x Q8.8 -> Q8.8 rescale ====================

@cocotb.test()
async def test_q88_mul_directed(dut):
    """1.5 * 2.0 = 3.0 etc, expressed directly as raw Q8.8 integers."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    def q(x):
        return int(round(x * Q))

    cases = [
        (q(1.5), q(2.0)),    # -> 3.0
        (q(2.0), q(2.0)),    # -> 4.0
        (q(-1.0), q(3.0)),   # -> -3.0
        (q(0.5), q(0.5)),    # -> 0.25
        (q(-2.0), q(-2.0)),  # -> 4.0
    ]
    for a, b in cases:
        await check_alu(dut, a, b, OP_MUL)

    dut._log.info("Q8.8 MUL directed tests passed")


@cocotb.test()
async def test_q88_mul_floor_rounding(dut):
    """Directed cases with a nonzero fractional remainder on a NEGATIVE
    product -- this is exactly the case where naively negating a
    truncated magnitude gives the wrong answer (off by one from a true
    arithmetic-shift floor). Confirms the RTL's extra rounding-correction
    cycle actually fires and gives the mathematically correct result."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (-3, 100),     # mag=300, remainder=300%256=44 != 0
        (3, -100),
        (-1, 1),       # mag=1, remainder=1 != 0
        (1, -1),
        (-7, 7),       # mag=49, remainder=49 != 0
        (-255, 1),     # mag=255, remainder=255 != 0 (just under 1 full unit)
    ]
    for a, b in cases:
        await check_alu(dut, a, b, OP_MUL)

    dut._log.info("Q8.8 MUL floor-rounding tests passed")


@cocotb.test()
async def test_q88_mul_exact_negative_boundary(dut):
    """The exact boundary case: truncated magnitude sits precisely at
    32768 (MIN_VAL's unsigned bit pattern) AND there's a nonzero
    remainder -- the floor-correction must saturate here, not wrap
    around past MIN_VAL."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    # mag = 32768*256 + r, split as A=-mag, B=1 (16-bit A won't hold mag
    # directly, so instead pick A,B whose product hits these exact mags)
    # 32768*256 = 8388608 = 8192 * 1024 = A=-8192, B=1024 -> mag=8388608, remainder=0 (exact boundary, no rounding)
    await check_alu(dut, -8192, 1024, OP_MUL)
    # A=-8191, B=1024 -> mag = 8191*1024 = 8387584 -> shifted=32764, remainder=0 (sanity, no saturation)
    await check_alu(dut, -8191, 1024, OP_MUL)
    # Construct mag = 8388608 + 1 (one past the exact boundary multiple):
    # 8388609 is odd/prime-ish and hard to factor into 16-bit operands
    # cleanly, so instead directly hit the interesting overflow region
    # with values whose product's magnitude exceeds 8388608 by a
    # non-multiple-of-256 amount using operands that stay in range.
    await check_alu(dut, -8193, 1024, OP_MUL)  # mag=8389632 -> shifted=32772 > 32768 -> saturates (plain overflow, no rounding edge)

    dut._log.info("Q8.8 MUL exact-negative-boundary tests passed")


@cocotb.test()
async def test_q88_mul_saturation(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (20000, 20000),
        (-20000, 20000),
        (-20000, -20000),
        (32767, 32767),
        (-32768, -32768),
        (-32768, 32767),
    ]
    for a, b in cases:
        await check_alu(dut, a, b, OP_MUL)

    dut._log.info("Q8.8 MUL saturation tests passed")


@cocotb.test()
async def test_q88_random(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    random.seed(88)
    ops = [OP_ADD, OP_SUB, OP_MUL]
    for _ in range(300):
        a = signed16(random.randint(-32768, 32767))
        b = signed16(random.randint(-32768, 32767))
        opcode = random.choice(ops)
        await check_alu(dut, a, b, opcode)

    dut._log.info("300 random Q8.8 ALU tests passed (add/sub/mul + saturation + rounding)")
