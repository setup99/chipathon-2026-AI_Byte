"""
cocotb testbench for the redesigned block_wrapper (mode-decoded
composition of ALU(Q8.8) / ReLU / Pool, with optional trailing Scale).

Mode table (bias_en, relu_en, pool_en sampled with the 1st word):
  0 0 0 -> ALU              (2 words: A,B)      -> alu_q88(alu_opcode) -> [scale]
  0 1 0 -> ReLU only        (1 word:  din)       -> ReLU -> [scale]
  0 0 1 -> Pool only        (4 words: A,B,C,D)   -> Pool(pool_op) -> [scale]
  0 1 1 -> ReLU->Pool       (4 words: A,B,C,D)   -> ReLU x4 -> Pool -> [scale]
  1 0 0 -> Bias ADD         (2 words: y,bias)    -> alu_q88 ADD -> [scale]
  1 1 0 -> FC Bias->ReLU    (2 words: y,bias)    -> alu_q88 ADD -> ReLU -> [scale]
  1 x 1 -> illegal: pool_en is forced OFF whenever bias_en=1

Every test case logs its full mode + inputs alongside the
got-vs-expected output so a run's log is a complete audit trail.
"""
import random
import cocotb
from cocotb.clock import Clock

from int16_test_utils import tick, signed_n

CLK_PERIOD_NS = 10
WIDTH = 16
FRAC = 8
OUT_WIDTH = 8
SCALE_SHIFT = 8

ALU_MAX = (1 << (WIDTH - 1)) - 1
ALU_MIN = -(1 << (WIDTH - 1))
OUT_MAX = (1 << (OUT_WIDTH - 1)) - 1
OUT_MIN = -(1 << (OUT_WIDTH - 1))

ADD, SUB, MUL = 0, 1, 2
POOL_MAX, POOL_AVG = 0, 1


def signed16(v):
    return signed_n(v, WIDTH)


def signed8(v):
    return signed_n(v, OUT_WIDTH)


# ---- software models mirroring the RTL sub-blocks exactly ----

def sw_alu(a, b, opcode):
    if opcode == ADD:
        raw = a + b
    elif opcode == SUB:
        raw = a - b
    elif opcode == MUL:
        raw = (a * b) >> FRAC  # Q8.8 rescale, arithmetic (floor) shift
    else:
        raw = 0
    overflow = 0
    if raw > ALU_MAX:
        raw, overflow = ALU_MAX, 1
    elif raw < ALU_MIN:
        raw, overflow = ALU_MIN, 1
    return raw, overflow


def sw_relu(x):
    return max(0, x)


def sw_pool(vals, pool_op):
    if pool_op == POOL_MAX:
        return max(vals)
    return sum(vals) >> 2  # arithmetic floor shift


def sw_scale(din):
    shifted = din >> SCALE_SHIFT
    overflow = 0
    if shifted > OUT_MAX:
        shifted, overflow = OUT_MAX, 1
    elif shifted < OUT_MIN:
        shifted, overflow = OUT_MIN, 1
    return shifted, overflow


def needed_words(bias_en, relu_en, pool_en_eff):
    if bias_en:
        return 2
    if pool_en_eff:
        return 4
    if relu_en:
        return 1
    return 2


def sw_operation(bias_en, relu_en, pool_en, alu_opcode, pool_op, operands, scale_en):
    """Full software model of one wrapper transaction, mirroring the
    mode table (including forcing pool off whenever bias_en=1)."""
    pool_en_eff = pool_en and not bias_en

    if bias_en:
        y, bias_ext = operands
        s, s_ovf = sw_alu(y, bias_ext, ADD)  # bias_en always forces ADD
        if relu_en:
            mid, mid_ovf = sw_relu(s), s_ovf
        else:
            mid, mid_ovf = s, s_ovf
    elif pool_en_eff:
        if relu_en:
            relu_out = [sw_relu(w) for w in operands]
            mid, mid_ovf = sw_pool(relu_out, pool_op), 0
        else:
            mid, mid_ovf = sw_pool(operands, pool_op), 0
    elif relu_en:
        mid, mid_ovf = sw_relu(operands[0]), 0
    else:
        mid, mid_ovf = sw_alu(operands[0], operands[1], alu_opcode)

    if scale_en:
        out, scale_ovf = sw_scale(mid)
        return out, True, (mid_ovf | scale_ovf)
    return mid, False, mid_ovf


async def reset_dut(dut):
    dut.rst.value = 1
    dut.bias_en.value = 0
    dut.relu_en.value = 0
    dut.pool_en.value = 0
    dut.alu_opcode.value = 0
    dut.pool_op.value = 0
    dut.scale_en.value = 0
    dut.in_data.value = 0
    dut.in_valid.value = 0
    dut.out_ready.value = 1  # accept output immediately by default
    await tick(dut)
    await tick(dut)
    await tick(dut)
    dut.rst.value = 0
    await tick(dut)


async def send_word(dut, value, first=False, bias_en=0, relu_en=0, pool_en=0,
                     alu_opcode=0, pool_op=0, scale_en=0):
    if first:
        dut.bias_en.value = bias_en
        dut.relu_en.value = relu_en
        dut.pool_en.value = pool_en
        dut.alu_opcode.value = alu_opcode
        dut.pool_op.value = pool_op
        dut.scale_en.value = scale_en
    dut.in_data.value = value & 0xFFFF
    dut.in_valid.value = 1

    while int(dut.in_ready.value) != 1:
        await tick(dut)
    await tick(dut)  # cross the edge that performs the transfer
    dut.in_valid.value = 0


async def send_operands(dut, bias_en, relu_en, pool_en, alu_opcode, pool_op,
                         scale_en, operands):
    for i, val in enumerate(operands):
        await send_word(dut, val, first=(i == 0), bias_en=bias_en, relu_en=relu_en,
                         pool_en=pool_en, alu_opcode=alu_opcode, pool_op=pool_op,
                         scale_en=scale_en)


async def recv_result(dut, timeout_ticks=60):
    for _ in range(timeout_ticks):
        if int(dut.out_valid.value) == 1:
            is_int8 = int(dut.out_is_int8.value)
            if is_int8:
                val = signed8(dut.out_data8.value.to_unsigned())
            else:
                val = signed16(dut.out_data16.value.to_unsigned())
            ovf = int(dut.out_overflow.value)
            await tick(dut)
            return val, is_int8, ovf
        await tick(dut)
    raise TimeoutError(f"out_valid did not assert within {timeout_ticks} ticks")


def mode_name(bias_en, relu_en, pool_en):
    pool_en_eff = pool_en and not bias_en
    if bias_en and relu_en:
        return "BIAS->RELU"
    if bias_en:
        return "BIAS"
    if relu_en and pool_en_eff:
        return "RELU->POOL"
    if pool_en_eff:
        return "POOL"
    if relu_en:
        return "RELU"
    return "ALU"


def log_op(dut, bias_en, relu_en, pool_en, alu_opcode, pool_op, scale_en,
           operands, got, got_int8, got_ovf, exp, exp_int8, exp_ovf):
    dut._log.info(
        f"  {mode_name(bias_en, relu_en, pool_en):<10} alu_op={alu_opcode} pool_op={pool_op} "
        f"scale_en={scale_en} operands={operands}  "
        f"got={got:>7} (int8={got_int8}, ovf={got_ovf})  "
        f"expected={exp:>7} (int8={exp_int8}, ovf={exp_ovf})"
    )


async def check_op(dut, bias_en, relu_en, pool_en, alu_opcode, pool_op, operands, scale_en):
    await send_operands(dut, bias_en, relu_en, pool_en, alu_opcode, pool_op, scale_en, operands)
    got, got_int8, got_ovf = await recv_result(dut)
    exp, exp_int8, exp_ovf = sw_operation(bias_en, relu_en, pool_en, alu_opcode, pool_op, operands, scale_en)

    log_op(dut, bias_en, relu_en, pool_en, alu_opcode, pool_op, scale_en,
           operands, got, got_int8, got_ovf, exp, exp_int8, exp_ovf)

    mode = mode_name(bias_en, relu_en, pool_en)
    assert got_int8 == exp_int8, f"{mode} operands={operands}: out_is_int8 got={got_int8} expected={exp_int8}"
    assert got == exp, f"{mode} operands={operands}: got={got} expected={exp}"
    assert got_ovf == exp_ovf, f"{mode} operands={operands}: overflow got={got_ovf} expected={exp_ovf}"
    return got, got_int8, got_ovf


# ==================== Mode 000: standalone ALU (Q8.8) ====================

@cocotb.test()
async def test_mode_alu_directed(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    def q(x):
        return int(round(x * 256))

    cases = [
        (ADD, (q(1.5), q(2.0))),
        (SUB, (q(5.0), q(2.5))),
        (MUL, (q(1.5), q(2.0))),   # -> 3.0
        (MUL, (q(-2.0), q(3.0))),  # -> -6.0
    ]
    for opcode, operands in cases:
        await check_op(dut, 0, 0, 0, opcode, 0, operands, scale_en=0)
        await check_op(dut, 0, 0, 0, opcode, 0, operands, scale_en=1)

    dut._log.info("ALU mode directed tests passed")


@cocotb.test()
async def test_mode_alu_saturation(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    await check_op(dut, 0, 0, 0, MUL, 0, (20000, 20000), scale_en=0)
    await check_op(dut, 0, 0, 0, MUL, 0, (20000, 20000), scale_en=1)
    await check_op(dut, 0, 0, 0, MUL, 0, (-3, 100), scale_en=0)  # floor-rounding case

    dut._log.info("ALU mode saturation/rounding tests passed")


# ==================== Mode 010: ReLU only ====================

@cocotb.test()
async def test_mode_relu_only(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    for x in [500, -500, 0, ALU_MAX, ALU_MIN]:
        await check_op(dut, 0, 1, 0, 0, 0, (x,), scale_en=0)
    for x in [2560, -2560]:
        await check_op(dut, 0, 1, 0, 0, 0, (x,), scale_en=1)

    dut._log.info("ReLU-only mode tests passed")


# ==================== Mode 001: Pool only ====================

@cocotb.test()
async def test_mode_pool_only(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (POOL_MAX, (1, 2, 0, -1)),
        (POOL_MAX, (-1, -2, -3, -4)),
        (POOL_AVG, (4, 2, 1, -1)),
        (POOL_AVG, (-1, 0, 0, 0)),
    ]
    for pool_op, operands in cases:
        await check_op(dut, 0, 0, 1, 0, pool_op, operands, scale_en=0)
    await check_op(dut, 0, 0, 1, 0, POOL_MAX, (2560, 1280, 0, -1280), scale_en=1)

    dut._log.info("Pool-only mode tests passed")


# ==================== Mode 011: ReLU -> Pool ====================

@cocotb.test()
async def test_mode_relu_then_pool(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (POOL_MAX, (100, -50, 200, -300)),   # ReLU zeroes the negatives, MAX picks 200
        (POOL_AVG, (100, -50, 200, -300)),   # ReLU zeroes negatives, AVG of (100,0,200,0)
        (POOL_MAX, (-1, -2, -3, -4)),        # all negative -> all zeroed -> max=0
        (POOL_AVG, (-1, -2, -3, -4)),        # all negative -> all zeroed -> avg=0
    ]
    for pool_op, operands in cases:
        await check_op(dut, 0, 1, 1, 0, pool_op, operands, scale_en=0)
    await check_op(dut, 0, 1, 1, 0, POOL_MAX, (2560, -50, 1280, -300), scale_en=1)

    dut._log.info("ReLU->Pool mode tests passed")


# ==================== Mode 100: Bias ADD ====================

@cocotb.test()
async def test_mode_bias_add(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    # y = SA INT16 accumulator, bias_ext = sign-extended INT8 bias
    cases = [
        (1000, 50),
        (-1000, -50),
        (32000, 1000),   # pushes toward saturation
        (0, 0),
    ]
    for y, bias_ext in cases:
        await check_op(dut, 1, 0, 0, 0, 0, (y, bias_ext), scale_en=0)
        await check_op(dut, 1, 0, 0, 0, 0, (y, bias_ext), scale_en=1)

    dut._log.info("Bias-ADD mode tests passed")


# ==================== Mode 110: FC Bias -> ReLU ====================

@cocotb.test()
async def test_mode_fc_bias_then_relu(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    cases = [
        (1000, 50),     # positive sum -> ReLU passes through
        (-1000, 50),    # negative sum -> ReLU zeroes it
        (100, -50),     # small positive sum
        (32700, 100),   # sum saturates positive before ReLU
    ]
    for y, bias_ext in cases:
        await check_op(dut, 1, 1, 0, 0, 0, (y, bias_ext), scale_en=0)
        await check_op(dut, 1, 1, 0, 0, 0, (y, bias_ext), scale_en=1)

    dut._log.info("FC Bias->ReLU mode tests passed")


# ==================== illegal combo: bias_en=1, pool_en=1 ====================

@cocotb.test()
async def test_illegal_bias_and_pool_combo(dut):
    """bias_en=1 with pool_en=1 is spec'd illegal; the wrapper forces
    pool off in that case, so this must behave exactly like plain
    Bias ADD (2 words, no pooling) despite pool_en being asserted."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    # Note: sw_operation already encodes "pool forced off when bias_en=1"
    await check_op(dut, 1, 0, 1, 0, POOL_MAX, (1000, 50), scale_en=0)
    await check_op(dut, 1, 1, 1, 0, POOL_AVG, (-1000, 50), scale_en=1)

    dut._log.info("Illegal bias+pool combo (pool forced off) test passed")


# ==================== internal-signal isolation checks ====================

@cocotb.test()
async def test_alu_mode_never_touches_relu_or_pool(dut):
    """Introspect internal valid signals during standalone ALU mode:
    ReLU and Pool must never activate."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    relu_fired = pool_fired = False
    await send_operands(dut, 0, 0, 0, ADD, 0, 0, (11, 22))
    for _ in range(20):
        if int(dut.u_relu.valid.value) == 1:
            relu_fired = True
        if int(dut.u_pool.valid.value) == 1:
            pool_fired = True
        if int(dut.out_valid.value) == 1:
            break
        await tick(dut)

    dut._log.info(f"  During ALU op: relu_valid={relu_fired} pool_valid={pool_fired} (both expected False)")
    assert not relu_fired, "ReLU should never activate during standalone ALU mode"
    assert not pool_fired, "Pool should never activate during standalone ALU mode"

    dut._log.info("ALU-mode isolation test passed")


@cocotb.test()
async def test_bias_mode_never_touches_pool(dut):
    """During any bias_en=1 mode, Pool must never activate (even if
    pool_en was asserted alongside it -- the illegal combo)."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    pool_fired = False
    await send_operands(dut, 1, 1, 1, 0, POOL_MAX, 0, (500, 20))  # bias+relu+pool(illegal)
    for _ in range(30):
        if int(dut.u_pool.valid.value) == 1:
            pool_fired = True
        if int(dut.out_valid.value) == 1:
            break
        await tick(dut)

    dut._log.info(f"  During bias-mode op with pool_en also asserted: pool_valid={pool_fired} (expected False)")
    assert not pool_fired, "Pool should never activate whenever bias_en=1"

    dut._log.info("Bias-mode pool-isolation test passed")


# ==================== back-to-back mixed modes ====================

@cocotb.test()
async def test_back_to_back_mixed_modes(dut):
    """Cycle through every mode back-to-back, confirming no leftover
    state (operand_reg, mid_result, loop indices) leaks between
    differently-shaped transactions."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    await check_op(dut, 0, 0, 0, ADD, 0, (300, 700), scale_en=0)          # ALU, 2 words
    await check_op(dut, 0, 0, 1, POOL_MAX, POOL_MAX, (9, 2, 7, -5), scale_en=0)  # Pool, 4 words
    await check_op(dut, 0, 1, 0, 0, 0, (-42,), scale_en=0)                # ReLU, 1 word
    await check_op(dut, 0, 1, 1, 0, POOL_AVG, (8, -8, 8, 8), scale_en=1)  # ReLU->Pool, 4 words
    await check_op(dut, 1, 0, 0, 0, 0, (1000, 50), scale_en=0)            # Bias, 2 words
    await check_op(dut, 1, 1, 0, 0, 0, (-1000, 50), scale_en=1)           # FC Bias->ReLU, 2 words
    await check_op(dut, 0, 0, 0, MUL, 0, (300, 400), scale_en=1)          # ALU MUL, 2 words

    dut._log.info("Back-to-back mixed-mode sequencing test passed")


# ==================== random, all modes mixed ====================

@cocotb.test()
async def test_random_all_modes(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())
    await reset_dut(dut)

    random.seed(2025)
    modes = ["ALU", "RELU", "POOL", "RELU_POOL", "BIAS", "FC_BIAS_RELU"]

    for _ in range(80):
        mode = random.choice(modes)
        scale_en = random.choice([0, 1])

        if mode == "ALU":
            bias_en, relu_en, pool_en = 0, 0, 0
            alu_opcode = random.choice([ADD, SUB, MUL])
            pool_op = 0
            operands = tuple(signed16(random.randint(-32768, 32767)) for _ in range(2))
        elif mode == "RELU":
            bias_en, relu_en, pool_en = 0, 1, 0
            alu_opcode, pool_op = 0, 0
            operands = (signed16(random.randint(-32768, 32767)),)
        elif mode == "POOL":
            bias_en, relu_en, pool_en = 0, 0, 1
            alu_opcode = 0
            pool_op = random.choice([POOL_MAX, POOL_AVG])
            operands = tuple(signed16(random.randint(-32768, 32767)) for _ in range(4))
        elif mode == "RELU_POOL":
            bias_en, relu_en, pool_en = 0, 1, 1
            alu_opcode = 0
            pool_op = random.choice([POOL_MAX, POOL_AVG])
            operands = tuple(signed16(random.randint(-32768, 32767)) for _ in range(4))
        elif mode == "BIAS":
            bias_en, relu_en, pool_en = 1, 0, 0
            alu_opcode, pool_op = 0, 0
            operands = tuple(signed16(random.randint(-32768, 32767)) for _ in range(2))
        else:  # FC_BIAS_RELU
            bias_en, relu_en, pool_en = 1, 1, 0
            alu_opcode, pool_op = 0, 0
            operands = tuple(signed16(random.randint(-32768, 32767)) for _ in range(2))

        await check_op(dut, bias_en, relu_en, pool_en, alu_opcode, pool_op, operands, scale_en)

    dut._log.info("80 random mixed-mode tests passed")
