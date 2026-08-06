"""
End-to-end opcode tests: chip_top (workshop pads) vs AiByteGolden.

Bit-exact: ALU, CONV/FC post+scale, illegal decode.
EML ops: Q8.8 / INT8 tolerance vs float golden (Mitchell approx.).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, ClockCycles
from cocotb.types import LogicArray

sys.path.insert(0, str(Path(__file__).resolve().parent))

from golden import (  # noqa: E402
    ADDR_CONTROL,
    ADDR_STATUS,
    ADDR_OPCODE,
    ADDR_CONFIG,
    ADDR_FEATURE_COLS,
    ADDR_SOFTMAX_N,
    AiByteGolden,
    BUF_ACT,
    BUF_RES,
    BUF_WT,
    CFG_BIAS,
    CFG_POOL,
    CFG_RELU,
    CFG_SCALE,
    OP_ADD,
    OP_CONV,
    OP_FC,
    OP_MICRO,
    OP_MUL,
    OP_RECIP,
    OP_SIGMOID,
    OP_SOFTMAX,
    OP_SQRT,
    OP_SUB,
    OP_TANH,
    compare_bytes,
    compare_q88_words,
    float_to_q88,
    pack_q88_bytes,
    unpack_q88_bytes,
)
from ai_byte_pads import (  # noqa: E402
    pin_write,
    pin_read,
    buf_write,
    buf_read,
    wait_irq,
)

GL = os.getenv("GL", "0") not in ("0", "false", "False", "")

TOL_EML_Q88 = 0x80  # 0.5 in Q8.8
TOL_EML_I8 = 2
TOL_SOFTMAX_I8 = 3
TOL_MICRO_Q88 = 0x80


async def start_up(dut, freq_mhz=50):
    try:
        dut.input_PAD.value = 0
    except Exception:
        pass
    if GL:
        dut.VDD.value = 1
        dut.VSS.value = 0
    bits = ["z"] * 20
    for i in range(14):
        bits[i] = "0"
    dut.bidir_PAD.value = LogicArray("".join(reversed(bits)))
    cocotb.start_soon(Clock(dut.clk_PAD, 1000.0 / freq_mhz, unit="ns").start())
    dut.rst_n_PAD.value = 0
    await Timer(200, unit="ns")
    dut.rst_n_PAD.value = 1
    await ClockCycles(dut.clk_PAD, 4)


async def dual_write_buf(dut, g: AiByteGolden, sel, addr, data):
    g.write_buf(sel, addr, data)
    await buf_write(dut, sel, addr, data)


async def dual_write_reg(dut, g: AiByteGolden, addr, data):
    if addr == ADDR_CONTROL and (data & 0x1):
        raise RuntimeError("use dual_start() for CONTROL START")
    g.write_reg(addr, data)
    await pin_write(dut, addr, data)


async def dual_start(dut, g: AiByteGolden, timeout=80000):
    g.write_reg(ADDR_CONTROL, 0x01)
    await pin_write(dut, ADDR_CONTROL, 0x01)
    await wait_irq(dut, timeout)


async def clear_irq(dut, g: AiByteGolden):
    g.write_reg(ADDR_CONTROL, 0x04)
    await pin_write(dut, ADDR_CONTROL, 0x04)


async def read_res_bytes(dut, n: int) -> list[int]:
    return [await buf_read(dut, BUF_RES, i) for i in range(n)]


def res_q88(bytes_le: list[int], index: int = 0) -> int:
    return unpack_q88_bytes(bytes_le[2 * index], bytes_le[2 * index + 1])


async def assert_status_match(dut, g: AiByteGolden, expect_error: bool = False):
    st_hw = await pin_read(dut, ADDR_STATUS)
    st_g = g.read_reg(ADDR_STATUS)
    err_hw = bool(st_hw & 0x1)
    err_g = bool(st_g & 0x1)
    assert err_hw == err_g == expect_error, (
        f"STATUS error mismatch: hw={st_hw:#x} gold={st_g:#x} expect_err={expect_error}"
    )
    if not expect_error:
        assert (st_hw & 0x2) != 0 or (st_g & 0x2) != 0, f"expected DONE bit hw={st_hw:#x}"


# ---------------------------------------------------------------------------
# Per-instruction e2e (pad MMIF)
# ---------------------------------------------------------------------------

@cocotb.test()
async def test_e2e_illegal(dut):
    """Opcode 0x5 → ERROR STATUS matches golden."""
    await start_up(dut)
    g = AiByteGolden()

    await dual_write_reg(dut, g, ADDR_OPCODE, 0x5)
    await dual_start(dut, g, timeout=2000)
    await assert_status_match(dut, g, expect_error=True)
    await clear_irq(dut, g)
    cocotb.log.info("e2e ILLEGAL: PASS (ERROR IRQ match)")


@cocotb.test()
async def test_e2e_add(dut):
    """ALU ADD 1.0+2.0 Q8.8 — bit-exact vs golden."""
    await start_up(dut)
    g = AiByteGolden()

    for sel, val in ((BUF_ACT, 1.0), (BUF_WT, 2.0)):
        lo, hi = pack_q88_bytes(float_to_q88(val))
        await dual_write_buf(dut, g, sel, 0, lo)
        await dual_write_buf(dut, g, sel, 1, hi)

    await dual_write_reg(dut, g, ADDR_FEATURE_COLS, 1)
    await dual_write_reg(dut, g, ADDR_CONFIG, 0)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_ADD)
    await dual_start(dut, g)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 2)
    gold = g.result_bytes(2)
    ok, msg = compare_bytes(hw, gold, tol=0)
    assert ok, f"ADD mismatch: {msg} hw={hw} gold={gold}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e ADD: PASS res={hw} {msg}")


@cocotb.test()
async def test_e2e_sub(dut):
    """ALU SUB 5.0-2.0 Q8.8 — bit-exact."""
    await start_up(dut)
    g = AiByteGolden()

    for sel, val in ((BUF_ACT, 5.0), (BUF_WT, 2.0)):
        lo, hi = pack_q88_bytes(float_to_q88(val))
        await dual_write_buf(dut, g, sel, 0, lo)
        await dual_write_buf(dut, g, sel, 1, hi)

    await dual_write_reg(dut, g, ADDR_FEATURE_COLS, 1)
    await dual_write_reg(dut, g, ADDR_CONFIG, 0)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_SUB)
    await dual_start(dut, g)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 2)
    gold = g.result_bytes(2)
    ok, msg = compare_bytes(hw, gold, tol=0)
    assert ok, f"SUB mismatch: {msg} hw={hw} gold={gold}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e SUB: PASS res={hw} {msg}")


@cocotb.test()
async def test_e2e_mul(dut):
    """ALU MUL 2.0*3.0 Q8.8 — bit-exact (floor mul)."""
    await start_up(dut)
    g = AiByteGolden()

    for sel, val in ((BUF_ACT, 2.0), (BUF_WT, 3.0)):
        lo, hi = pack_q88_bytes(float_to_q88(val))
        await dual_write_buf(dut, g, sel, 0, lo)
        await dual_write_buf(dut, g, sel, 1, hi)

    await dual_write_reg(dut, g, ADDR_FEATURE_COLS, 1)
    await dual_write_reg(dut, g, ADDR_CONFIG, 0)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_MUL)
    await dual_start(dut, g)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 2)
    gold = g.result_bytes(2)
    ok, msg = compare_bytes(hw, gold, tol=0)
    assert ok, f"MUL mismatch: {msg} hw={hw} gold={gold}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e MUL: PASS res={hw} {msg}")


@cocotb.test()
async def test_e2e_sqrt(dut):
    """SQRT(4.0) vs float golden within TOL_EML_Q88."""
    await start_up(dut)
    g = AiByteGolden()

    lo, hi = pack_q88_bytes(float_to_q88(4.0))
    await dual_write_buf(dut, g, BUF_ACT, 0, lo)
    await dual_write_buf(dut, g, BUF_ACT, 1, hi)
    await dual_write_reg(dut, g, ADDR_FEATURE_COLS, 1)
    await dual_write_reg(dut, g, ADDR_CONFIG, 0)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_SQRT)
    await dual_start(dut, g, timeout=20000)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 2)
    gold = g.result_bytes(2)
    ok, msg = compare_q88_words([res_q88(hw)], [res_q88(gold)], tol=TOL_EML_Q88)
    assert ok, f"SQRT mismatch: {msg} hw={res_q88(hw):#x} gold={res_q88(gold):#x}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e SQRT: PASS hw={res_q88(hw):#x} gold={res_q88(gold):#x} {msg}")


@cocotb.test()
async def test_e2e_recip(dut):
    """RECIP(0.5)=2.0 approx vs float golden."""
    await start_up(dut)
    g = AiByteGolden()

    lo, hi = pack_q88_bytes(float_to_q88(0.5))
    await dual_write_buf(dut, g, BUF_ACT, 0, lo)
    await dual_write_buf(dut, g, BUF_ACT, 1, hi)
    await dual_write_reg(dut, g, ADDR_FEATURE_COLS, 1)
    await dual_write_reg(dut, g, ADDR_CONFIG, 0)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_RECIP)
    await dual_start(dut, g, timeout=20000)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 2)
    gold = g.result_bytes(2)
    ok, msg = compare_q88_words([res_q88(hw)], [res_q88(gold)], tol=TOL_EML_Q88)
    assert ok, f"RECIP mismatch: {msg} hw={res_q88(hw):#x} gold={res_q88(gold):#x}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e RECIP: PASS hw={res_q88(hw):#x} gold={res_q88(gold):#x} {msg}")


@cocotb.test()
async def test_e2e_sigmoid(dut):
    """SIGMOID zeros → INT8 vs golden (tolerance)."""
    await start_up(dut)
    g = AiByteGolden()

    for i in range(16):
        await dual_write_buf(dut, g, BUF_ACT, i, 0)
    await dual_write_reg(dut, g, ADDR_FEATURE_COLS, 16)
    await dual_write_reg(dut, g, ADDR_CONFIG, 0)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_SIGMOID)
    await dual_start(dut, g, timeout=40000)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 16)
    gold = g.result_bytes(16)
    ok, msg = compare_bytes(hw, gold, tol=TOL_EML_I8)
    assert ok, f"SIGMOID mismatch: {msg}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e SIGMOID: PASS first4_hw={hw[:4]} gold={gold[:4]} {msg}")


@cocotb.test()
async def test_e2e_tanh(dut):
    """TANH zeros → 0 INT8 vs golden."""
    await start_up(dut)
    g = AiByteGolden()

    for i in range(16):
        await dual_write_buf(dut, g, BUF_ACT, i, 0)
    await dual_write_reg(dut, g, ADDR_FEATURE_COLS, 16)
    await dual_write_reg(dut, g, ADDR_CONFIG, 0)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_TANH)
    await dual_start(dut, g, timeout=40000)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 16)
    gold = g.result_bytes(16)
    ok, msg = compare_bytes(hw, gold, tol=TOL_EML_I8)
    assert ok, f"TANH mismatch: {msg}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e TANH: PASS first4_hw={hw[:4]} gold={gold[:4]} {msg}")


@cocotb.test()
async def test_e2e_softmax(dut):
    """Softmax N=4 equal inputs vs float golden (scaled INT8)."""
    await start_up(dut)
    g = AiByteGolden()

    n = 4
    for i in range(n):
        await dual_write_buf(dut, g, BUF_ACT, i, 0)
    await dual_write_reg(dut, g, ADDR_SOFTMAX_N, n)
    await dual_write_reg(dut, g, ADDR_CONFIG, 1 << 5)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_SOFTMAX)
    await dual_start(dut, g, timeout=50000)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, n)
    gold = g.result_bytes(n)
    ok, msg = compare_bytes(hw, gold, tol=TOL_SOFTMAX_I8)
    assert ok, f"SOFTMAX mismatch: {msg} hw={hw} gold={gold}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e SOFTMAX: PASS hw={hw} gold={gold} {msg}")


@cocotb.test()
async def test_e2e_microprog(dut):
    """FEEDBACK one step: exp(0)-ln(1) ≈ 1.0 Q8.8."""
    await start_up(dut)
    g = AiByteGolden()

    lo, hi = pack_q88_bytes(float_to_q88(1.0))
    await dual_write_buf(dut, g, BUF_WT, 0, lo)
    await dual_write_buf(dut, g, BUF_WT, 1, hi)
    lo, hi = pack_q88_bytes(float_to_q88(0.0))
    await dual_write_buf(dut, g, BUF_WT, 2, lo)
    await dual_write_buf(dut, g, BUF_WT, 3, hi)
    await dual_write_buf(dut, g, BUF_ACT, 0, 0x08)
    await dual_write_reg(dut, g, ADDR_FEATURE_COLS, 1)
    await dual_write_reg(dut, g, ADDR_CONFIG, 0)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_MICRO)
    await dual_start(dut, g, timeout=20000)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 2)
    gold = g.result_bytes(2)
    ok, msg = compare_q88_words([res_q88(hw)], [res_q88(gold)], tol=TOL_MICRO_Q88)
    assert ok, f"MICRO mismatch: {msg} hw={res_q88(hw):#x} gold={res_q88(gold):#x}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e MICRO: PASS hw={res_q88(hw):#x} gold={res_q88(gold):#x} {msg}")


@cocotb.test()
async def test_e2e_fc(dut):
    """FC W≈I, X=2, bias0, relu, scale → bit-exact INT8 vs golden."""
    await start_up(dut)
    g = AiByteGolden()

    for i in range(16):
        await dual_write_buf(dut, g, BUF_WT, i, 1 if (i % 5 == 0) else 0)
        await dual_write_buf(dut, g, BUF_ACT, i, 2)
        await dual_write_buf(dut, g, BUF_ACT, 16 + i, 0)

    cfg = CFG_BIAS | CFG_RELU | CFG_SCALE
    await dual_write_reg(dut, g, ADDR_CONFIG, cfg)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_FC)
    await dual_start(dut, g, timeout=80000)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 16)
    gold = g.result_bytes(16)
    ok, msg = compare_bytes(hw, gold, tol=0)
    assert ok, f"FC mismatch: {msg} hw={hw} gold={gold}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e FC: PASS first8_hw={hw[:8]} gold={gold[:8]} {msg}")


@cocotb.test()
async def test_e2e_conv(dut):
    """CONV ones + relu+pool+scale → 4 INT8 outs bit-exact vs golden."""
    await start_up(dut)
    g = AiByteGolden()

    for i in range(16):
        await dual_write_buf(dut, g, BUF_WT, i, 1)
        await dual_write_buf(dut, g, BUF_ACT, i, 1)

    cfg = CFG_RELU | CFG_POOL | CFG_SCALE
    await dual_write_reg(dut, g, ADDR_CONFIG, cfg)
    await dual_write_reg(dut, g, ADDR_OPCODE, OP_CONV)
    await dual_start(dut, g, timeout=80000)
    await assert_status_match(dut, g)

    hw = await read_res_bytes(dut, 4)
    gold = g.result_bytes(4)
    ok, msg = compare_bytes(hw, gold, tol=0)
    assert ok, f"CONV mismatch: {msg} hw={hw} gold={gold}"
    await clear_irq(dut, g)
    cocotb.log.info(f"e2e CONV: PASS hw={hw} gold={gold} {msg}")
