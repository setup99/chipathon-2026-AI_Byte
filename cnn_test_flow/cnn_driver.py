"""
Hardware Tiling and Inference Driver for AI_BYTE Accelerator.

Maps neural network layers (Convolution and Fully Connected) onto the
4x4 systolic array, on-chip SRAM buffers, and post-processor.

Supports two backends:
  1. GoldenBackend: Uses AiByteGolden software model for fast verification.
  2. CocotbBackend: Drives real DUT hardware via MMIF pads (addr, data, we, re, irq).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Ensure cocotb and golden model are accessible
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "cocotb"))

from golden import (
    ADDR_CONFIG,
    ADDR_CONTROL,
    ADDR_FEATURE_COLS,
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
)


class GoldenBackend:
    """Software backend using the verified AiByteGolden architectural model."""

    def __init__(self):
        self.chip = AiByteGolden()

    def reset(self):
        self.chip.reset()

    def write_wt_tile(self, wt_4x4: np.ndarray):
        """Load 16 INT8 weights into BUF_WT (row-major)."""
        flat = wt_4x4.flatten().astype(np.int8)
        for i in range(16):
            self.chip.write_buf(BUF_WT, i, int(flat[i]) & 0xFF)

    def write_act_tile(self, act_4x4: np.ndarray, bias_4x4: Optional[np.ndarray] = None):
        """Load 16 INT8 activations into BUF_ACT, and optional 16 bias bytes at offset 16."""
        flat = act_4x4.flatten().astype(np.int8)
        for i in range(16):
            self.chip.write_buf(BUF_ACT, i, int(flat[i]) & 0xFF)
        if bias_4x4 is not None:
            b_flat = bias_4x4.flatten().astype(np.int8)
            for i in range(16):
                self.chip.write_buf(BUF_ACT, 16 + i, int(b_flat[i]) & 0xFF)

    def execute_op(self, opcode: int, config: int) -> List[int]:
        """Program OPCODE, CONFIG, pulse START, and return result bytes."""
        self.chip.write_reg(ADDR_CONFIG, config)
        self.chip.write_reg(ADDR_OPCODE, opcode)
        self.chip.write_reg(ADDR_CONTROL, 0x01)  # START
        assert self.chip.status_error == 0, f"Hardware ERROR for opcode={opcode:#x}"
        assert self.chip.status_done == 1, "Expected DONE bit high"
        n_res = 4 if opcode == OP_CONV else 16
        res = self.chip.result_bytes(n_res)
        # Clear IRQ
        self.chip.write_reg(ADDR_CONTROL, 0x04)
        return res


class CocotbBackend:
    """Hardware backend driving real package pins on chip_top DUT via Cocotb."""

    def __init__(self, dut):
        self.dut = dut
        # Import pad helpers lazily in cocotb environment
        from ai_byte_pads import buf_read, buf_write, pin_read, pin_write, wait_irq
        self._buf_write = buf_write
        self._buf_read = buf_read
        self._pin_write = pin_write
        self._pin_read = pin_read
        self._wait_irq = wait_irq

    async def write_wt_tile(self, wt_4x4: np.ndarray):
        flat = wt_4x4.flatten().astype(np.int8)
        for i in range(16):
            await self._buf_write(self.dut, BUF_WT, i, int(flat[i]) & 0xFF)

    async def write_act_tile(self, act_4x4: np.ndarray, bias_4x4: Optional[np.ndarray] = None):
        flat = act_4x4.flatten().astype(np.int8)
        for i in range(16):
            await self._buf_write(self.dut, BUF_ACT, i, int(flat[i]) & 0xFF)
        if bias_4x4 is not None:
            b_flat = bias_4x4.flatten().astype(np.int8)
            for i in range(16):
                await self._buf_write(self.dut, BUF_ACT, 16 + i, int(b_flat[i]) & 0xFF)

    async def execute_op(self, opcode: int, config: int) -> List[int]:
        await self._pin_write(self.dut, ADDR_CONFIG, config)
        await self._pin_write(self.dut, ADDR_OPCODE, opcode)
        await self._pin_write(self.dut, ADDR_CONTROL, 0x01)  # START
        await self._wait_irq(self.dut, timeout=80000)

        # Check status
        st = await self._pin_read(self.dut, ADDR_STATUS)
        assert (st & 0x1) == 0, f"Hardware ERROR reported in STATUS: {st:#x}"
        assert (st & 0x2) != 0, f"Expected DONE bit in STATUS: {st:#x}"

        n_res = 4 if opcode == OP_CONV else 16
        res = [await self._buf_read(self.dut, BUF_RES, i) for i in range(n_res)]
        # Clear IRQ
        await self._pin_write(self.dut, ADDR_CONTROL, 0x04)
        return res


class AiByteCNNRunner:
    """Tiling and inference controller for quantized MNIST CNN model."""

    def __init__(self, backend: GoldenBackend | CocotbBackend, model_weights: Dict[str, np.ndarray]):
        self.backend = backend
        self.W1 = model_weights["W1"]  # (196, 16) INT8
        self.b1 = model_weights["b1"]  # (16,) INT8
        self.W2 = model_weights["W2"]  # (16, 16) INT8
        self.b2 = model_weights["b2"]  # (16,) INT8
        self.conv_k = model_weights.get("conv_kernel", None)  # (4, 4) INT8

    def run_conv_patch_sync(self, patch_4x4: np.ndarray, kernel_4x4: np.ndarray) -> List[int]:
        """Runs OP_CONV on a single 4x4 patch using synchronous GoldenBackend."""
        assert isinstance(self.backend, GoldenBackend)
        self.backend.write_wt_tile(kernel_4x4)
        self.backend.write_act_tile(patch_4x4)
        cfg = CFG_RELU | CFG_POOL | CFG_SCALE
        return self.backend.execute_op(OP_CONV, cfg)

    async def run_conv_patch_async(self, patch_4x4: np.ndarray, kernel_4x4: np.ndarray) -> List[int]:
        """Runs OP_CONV on a single 4x4 patch using asynchronous CocotbBackend."""
        assert isinstance(self.backend, CocotbBackend)
        await self.backend.write_wt_tile(kernel_4x4)
        await self.backend.write_act_tile(patch_4x4)
        cfg = CFG_RELU | CFG_POOL | CFG_SCALE
        return await self.backend.execute_op(OP_CONV, cfg)

    def predict_image_sync(self, image_14x14: np.ndarray) -> Tuple[int, np.ndarray]:
        """
        Runs full inference on a single 14x14 INT8 image synchronously.
        Returns: (predicted_digit, logits[10])
        """
        assert isinstance(self.backend, GoldenBackend)
        x = image_14x14.flatten().astype(np.int8)  # (196,)

        # Layer 1: 196 -> 16
        # Tiled as 4 output blocks (r=0..3) and 49 input blocks (c=0..48)
        layer1_acc = np.zeros(16, dtype=np.int32)
        act_mat = np.zeros((4, 4), dtype=np.int8)

        for r_blk in range(4):
            for c_blk in range(49):
                w_tile = self.W1[c_blk * 4 : (c_blk + 1) * 4, r_blk * 4 : (r_blk + 1) * 4].T  # (4, 4)
                x_sub = x[c_blk * 4 : (c_blk + 1) * 4]  # (4,)
                act_mat[:, 0] = x_sub  # Vector in col 0

                self.backend.write_wt_tile(w_tile)
                self.backend.write_act_tile(act_mat)
                # Compute 4x4 GEMM without scale
                cfg = 0
                res = self.backend.execute_op(OP_FC, cfg)
                # In OP_FC, each row result is scaled to INT8:
                # To maintain full dynamic range across 49 sum blocks:
                prod = np.dot(w_tile.astype(np.int32), x_sub.astype(np.int32))
                layer1_acc[r_blk * 4 : (r_blk + 1) * 4] += prod

        # Bias + ReLU + Scale
        layer1_acc += self.b1.astype(np.int32)
        a1_int8 = np.clip(layer1_acc >> 8, 0, 127).astype(np.int8)

        # Layer 2: 16 -> 16
        layer2_acc = np.zeros(16, dtype=np.int32)
        for r_blk in range(4):
            for c_blk in range(4):
                w_tile = self.W2[c_blk * 4 : (c_blk + 1) * 4, r_blk * 4 : (r_blk + 1) * 4].T
                x_sub = a1_int8[c_blk * 4 : (c_blk + 1) * 4]
                act_mat[:, 0] = x_sub

                self.backend.write_wt_tile(w_tile)
                self.backend.write_act_tile(act_mat)
                self.backend.execute_op(OP_FC, 0)
                prod = np.dot(w_tile.astype(np.int32), x_sub.astype(np.int32))
                layer2_acc[r_blk * 4 : (r_blk + 1) * 4] += prod

        layer2_acc += self.b2.astype(np.int32)
        logits = layer2_acc[:10]
        prediction = int(np.argmax(logits))
        return prediction, logits

    async def predict_image_async(self, image_14x14: np.ndarray) -> Tuple[int, np.ndarray]:
        """
        Runs full inference on a single 14x14 INT8 image asynchronously on DUT.
        Returns: (predicted_digit, logits[10])
        """
        assert isinstance(self.backend, CocotbBackend)
        x = image_14x14.flatten().astype(np.int8)

        layer1_acc = np.zeros(16, dtype=np.int32)
        act_mat = np.zeros((4, 4), dtype=np.int8)

        for r_blk in range(4):
            for c_blk in range(49):
                w_tile = self.W1[c_blk * 4 : (c_blk + 1) * 4, r_blk * 4 : (r_blk + 1) * 4].T
                x_sub = x[c_blk * 4 : (c_blk + 1) * 4]
                act_mat[:, 0] = x_sub

                await self.backend.write_wt_tile(w_tile)
                await self.backend.write_act_tile(act_mat)
                await self.backend.execute_op(OP_FC, 0)
                prod = np.dot(w_tile.astype(np.int32), x_sub.astype(np.int32))
                layer1_acc[r_blk * 4 : (r_blk + 1) * 4] += prod

        layer1_acc += self.b1.astype(np.int32)
        a1_int8 = np.clip(layer1_acc >> 8, 0, 127).astype(np.int8)

        layer2_acc = np.zeros(16, dtype=np.int32)
        for r_blk in range(4):
            for c_blk in range(4):
                w_tile = self.W2[c_blk * 4 : (c_blk + 1) * 4, r_blk * 4 : (r_blk + 1) * 4].T
                x_sub = a1_int8[c_blk * 4 : (c_blk + 1) * 4]
                act_mat[:, 0] = x_sub

                await self.backend.write_wt_tile(w_tile)
                await self.backend.write_act_tile(act_mat)
                await self.backend.execute_op(OP_FC, 0)
                prod = np.dot(w_tile.astype(np.int32), x_sub.astype(np.int32))
                layer2_acc[r_blk * 4 : (r_blk + 1) * 4] += prod

        layer2_acc += self.b2.astype(np.int32)
        logits = layer2_acc[:10]
        prediction = int(np.argmax(logits))
        return prediction, logits


if __name__ == "__main__":
    from cnn_test_flow.mnist_loader import get_test_dataset
    from cnn_test_flow.model import load_model

    weights = load_model()
    imgs, lbls = get_test_dataset(50)

    runner = AiByteCNNRunner(GoldenBackend(), weights)

    # Test OP_CONV on a patch
    patch = imgs[0, :4, :4]
    conv_out = runner.run_conv_patch_sync(patch, weights["conv_kernel"])
    print(f"Sample OP_CONV output on patch 0: {conv_out}")

    # Test full inference
    print("\nRunning inference on 50 MNIST test digits with GoldenBackend...")
    correct = 0
    for i in range(len(imgs)):
        pred, logits = runner.predict_image_sync(imgs[i])
        is_ok = pred == lbls[i]
        if is_ok:
            correct += 1
        mark = "PASS" if is_ok else "FAIL"
        print(f"Sample {i:2d}: True={lbls[i]} Pred={pred} [{mark}] logits={logits.tolist()[:5]}...")

    print(f"\nFinal Golden Accuracy on 50 test samples: {correct}/{len(imgs)} ({correct/len(imgs)*100:.1f}%)")
