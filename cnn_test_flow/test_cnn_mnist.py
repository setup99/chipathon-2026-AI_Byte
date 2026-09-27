"""
Cocotb RTL Verification for CNN Inference on MNIST with AI_BYTE Accelerator.

Tests full hardware chip_top against AiByteGolden and true MNIST labels:
  1. test_mnist_conv_tile: Bit-exact OP_CONV (4x4 GEMM + ReLU + 2x2 MaxPool + Scale).
  2. test_mnist_fc_tile: Bit-exact OP_FC (4x4 GEMM + Bias + ReLU + Scale).
  3. test_mnist_classification: Full end-to-end digit classification on real MNIST images.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Timer
from cocotb.types import LogicArray
import numpy as np

# Ensure parent cocotb paths are visible
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "cocotb"))
sys.path.insert(0, str(REPO_ROOT))

from ai_byte_pads import buf_read, buf_write, pin_read, pin_write, wait_irq
from golden import (
    ADDR_CONFIG,
    ADDR_CONTROL,
    ADDR_OPCODE,
    ADDR_STATUS,
    AiByteGolden,
    BUF_ACT,
    BUF_RES,
    BUF_WT,
    CFG_BIAS,
    CFG_POOL,
    CFG_RELU,
    CFG_SCALE,
    OP_CONV,
    OP_FC,
    compare_bytes,
)
from cnn_test_flow.cnn_driver import AiByteCNNRunner, CocotbBackend, GoldenBackend
from cnn_test_flow.mnist_loader import get_test_dataset
from cnn_test_flow.model import load_model

GL = os.getenv("GL", "0") not in ("0", "false", "False", "")


async def start_up(dut, freq_mhz=50):
    """Brings up DUT clock, reset, and pad initial conditions."""
    try:
        dut.input_PAD.value = 0
    except Exception:
        pass
    if GL:
        try:
            dut.VDD.value = 1
            dut.VSS.value = 0
        except AttributeError:
            pass

    bits = ["z"] * 20
    for i in range(14):
        bits[i] = "0"
    dut.bidir_PAD.value = LogicArray("".join(reversed(bits)))
    cocotb.start_soon(Clock(dut.clk_PAD, 1000.0 / freq_mhz, unit="ns").start())

    dut.rst_n_PAD.value = 0
    await Timer(200, unit="ns")
    dut.rst_n_PAD.value = 1
    await ClockCycles(dut.clk_PAD, 4)


@cocotb.test()
async def test_mnist_conv_tile(dut):
    """Verifies OP_CONV on a real MNIST 4x4 image patch vs Golden model."""
    await start_up(dut)
    weights = load_model()
    kernel = weights["conv_kernel"]  # (4, 4) INT8

    imgs, lbls = get_test_dataset(1)
    patch = imgs[0, 4:8, 4:8]  # (4, 4) INT8 from center of digit

    # 1. Drive DUT hardware
    flat_w = kernel.flatten().astype(np.int8)
    flat_x = patch.flatten().astype(np.int8)

    for i in range(16):
        await buf_write(dut, BUF_WT, i, int(flat_w[i]) & 0xFF)
        await buf_write(dut, BUF_ACT, i, int(flat_x[i]) & 0xFF)

    cfg = CFG_RELU | CFG_POOL | CFG_SCALE
    await pin_write(dut, ADDR_CONFIG, cfg)
    await pin_write(dut, ADDR_OPCODE, OP_CONV)
    await pin_write(dut, ADDR_CONTROL, 0x01)  # START
    await wait_irq(dut, timeout=40000)

    # Read status and result from DUT
    st = await pin_read(dut, ADDR_STATUS)
    assert (st & 0x1) == 0, f"Hardware ERROR reported in STATUS: {st:#x}"
    assert (st & 0x2) != 0, f"Expected DONE in STATUS: {st:#x}"

    hw_res = [await buf_read(dut, BUF_RES, i) for i in range(4)]
    await pin_write(dut, ADDR_CONTROL, 0x04)  # Clear IRQ

    # 2. Run software Golden model on identical inputs
    golden_runner = AiByteCNNRunner(GoldenBackend(), weights)
    gold_res = golden_runner.run_conv_patch_sync(patch, kernel)

    ok, msg = compare_bytes(hw_res, gold_res, tol=0)
    assert ok, f"OP_CONV mismatch vs golden: {msg} hw={hw_res} gold={gold_res}"
    cocotb.log.info(f"test_mnist_conv_tile: PASS hw={hw_res} gold={gold_res} {msg}")


@cocotb.test()
async def test_mnist_fc_tile(dut):
    """Verifies OP_FC on a 4x4 tile from the MNIST classifier vs Golden model."""
    await start_up(dut)
    weights = load_model()
    W2 = weights["W2"]  # (16, 16) INT8
    b2 = weights["b2"]  # (16,) INT8

    w_tile = W2[:4, :4]  # (4, 4)
    x_tile = np.array([10, -20, 30, 40], dtype=np.int8)
    act_mat = np.zeros((4, 4), dtype=np.int8)
    act_mat[:, 0] = x_tile
    bias_mat = np.zeros((4, 4), dtype=np.int8)
    bias_mat[:, 0] = b2[:4]

    flat_w = w_tile.flatten()
    flat_x = act_mat.flatten()
    flat_b = bias_mat.flatten()

    for i in range(16):
        await buf_write(dut, BUF_WT, i, int(flat_w[i]) & 0xFF)
        await buf_write(dut, BUF_ACT, i, int(flat_x[i]) & 0xFF)
        await buf_write(dut, BUF_ACT, 16 + i, int(flat_b[i]) & 0xFF)

    cfg = CFG_BIAS | CFG_RELU | CFG_SCALE
    await pin_write(dut, ADDR_CONFIG, cfg)
    await pin_write(dut, ADDR_OPCODE, OP_FC)
    await pin_write(dut, ADDR_CONTROL, 0x01)  # START
    await wait_irq(dut, timeout=40000)

    st = await pin_read(dut, ADDR_STATUS)
    assert (st & 0x1) == 0, f"Hardware ERROR reported in STATUS: {st:#x}"
    assert (st & 0x2) != 0, f"Expected DONE in STATUS: {st:#x}"

    hw_res = [await buf_read(dut, BUF_RES, i) for i in range(16)]
    await pin_write(dut, ADDR_CONTROL, 0x04)  # Clear IRQ

    # Golden comparison
    g = AiByteGolden()
    for i in range(16):
        g.write_buf(BUF_WT, i, int(flat_w[i]) & 0xFF)
        g.write_buf(BUF_ACT, i, int(flat_x[i]) & 0xFF)
        g.write_buf(BUF_ACT, 16 + i, int(flat_b[i]) & 0xFF)
    g.write_reg(ADDR_CONFIG, cfg)
    g.write_reg(ADDR_OPCODE, OP_FC)
    g.write_reg(ADDR_CONTROL, 0x01)
    gold_res = g.result_bytes(16)

    ok, msg = compare_bytes(hw_res, gold_res, tol=0)
    assert ok, f"OP_FC mismatch vs golden: {msg} hw={hw_res} gold={gold_res}"
    cocotb.log.info(f"test_mnist_fc_tile: PASS hw={hw_res[:4]} gold={gold_res[:4]} {msg}")


@cocotb.test()
async def test_mnist_classification(dut):
    """Runs full end-to-end digit classification on real MNIST images on hardware."""
    await start_up(dut)
    weights = load_model()

    # Test 5 real MNIST test digits: [7, 2, 1, 0, 4]
    num_test_digits = 5
    imgs, lbls = get_test_dataset(num_test_digits)

    hw_runner = AiByteCNNRunner(CocotbBackend(dut), weights)
    gold_runner = AiByteCNNRunner(GoldenBackend(), weights)

    correct = 0
    for idx in range(num_test_digits):
        true_label = int(lbls[idx])
        test_img = imgs[idx]

        # Run RTL hardware inference
        hw_pred, hw_logits = await hw_runner.predict_image_async(test_img)

        # Run Golden model inference
        gold_pred, gold_logits = gold_runner.predict_image_sync(test_img)

        # Assert bit-for-bit exact logit match between hardware and golden
        np.testing.assert_array_equal(
            hw_logits,
            gold_logits,
            err_msg=f"Digit {idx}: HW logits != Golden logits (hw={hw_logits} vs gold={gold_logits})",
        )

        # Assert prediction matches true MNIST ground-truth label
        is_correct = hw_pred == true_label
        if is_correct:
            correct += 1

        cocotb.log.info(
            f"MNIST Digit {idx}: True={true_label}, HW_Pred={hw_pred}, Gold_Pred={gold_pred} "
            f"[{'PASS' if is_correct else 'FAIL'}]"
        )
        assert is_correct, f"Digit {idx} misclassified: expected {true_label}, got {hw_pred}"

    cocotb.log.info(f"End-to-End Classification: {correct}/{num_test_digits} correct (100%)")
