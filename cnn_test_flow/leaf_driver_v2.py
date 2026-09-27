"""
Hardware Tiling and Inference Driver for PlantVillage Leaf Disease v2 (4-Class Multi-Disease) on AI_BYTE Accelerator.

Supports 4-Class Classifier (Healthy, Early Blight, Late Blight, Bacterial Spot):
  - Layer 1: FC(768 -> 64) + ReLU + Scale (>>> 8)
  - Layer 2: FC(64 -> 4) + Bias (100% hardware array utilization, all 4 outputs active)
  - EML Post-Processor: OP_SOFTMAX with N=4 for on-chip infection probability normalization
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "cocotb"))

from golden import (
    ADDR_CONFIG, ADDR_CONTROL, ADDR_OPCODE, ADDR_STATUS, ADDR_SOFTMAX_N,
    AiByteGolden, BUF_ACT, BUF_RES, BUF_WT,
    CFG_BIAS, CFG_POOL, CFG_RELU, CFG_SCALE,
    OP_CONV, OP_FC, OP_SOFTMAX,
)
from .cnn_driver import GoldenBackend, CocotbBackend


class AiByteLeafRunnerV2:
    """Tiling and inference controller for quantized 4-class Leaf Disease v2 model."""

    def __init__(self, backend: GoldenBackend | CocotbBackend, model_weights: Dict[str, np.ndarray]):
        self.backend = backend
        self.W1 = model_weights["W1"]  # (768, 64) INT8
        self.b1 = model_weights["b1"]  # (64,) INT8
        self.W2 = model_weights["W2"]  # (64, 4) INT8
        self.b2 = model_weights["b2"]  # (4,) INT8
        self.num_classes = 4

    def predict_image_sync(self, image_16x16x3: np.ndarray) -> Tuple[int, np.ndarray]:
        """Runs full inference on a single 16x16x3 INT8 leaf image synchronously via GoldenBackend."""
        assert isinstance(self.backend, GoldenBackend)
        x = image_16x16x3.flatten().astype(np.int8)

        n_in = 768
        n_hid = self.W1.shape[1]      # 64
        n_out = self.W2.shape[1]      # 4

        # Layer 1: 768 -> 64
        n_in_blks = n_in // 4    # 192
        n_hid_blks = n_hid // 4  # 16
        layer1_acc = np.zeros(n_hid, dtype=np.int32)
        act_mat = np.zeros((4, 4), dtype=np.int8)

        for r_blk in range(n_hid_blks):
            for c_blk in range(n_in_blks):
                w_tile = self.W1[c_blk*4:(c_blk+1)*4, r_blk*4:(r_blk+1)*4].T
                x_sub = x[c_blk*4:(c_blk+1)*4]
                act_mat[:, 0] = x_sub

                self.backend.write_wt_tile(w_tile)
                self.backend.write_act_tile(act_mat)
                self.backend.execute_op(OP_FC, 0)
                prod = np.dot(w_tile.astype(np.int32), x_sub.astype(np.int32))
                layer1_acc[r_blk*4:(r_blk+1)*4] += prod

        layer1_acc += self.b1.astype(np.int32)
        a1_int8 = np.clip(layer1_acc >> 8, 0, 127).astype(np.int8)

        # Layer 2: 64 -> 4
        n_hid_blks2 = n_hid // 4  # 16
        n_out_blks = n_out // 4   # 1
        layer2_acc = np.zeros(n_out, dtype=np.int32)

        for r_blk in range(n_out_blks):
            for c_blk in range(n_hid_blks2):
                w_tile = self.W2[c_blk*4:(c_blk+1)*4, r_blk*4:(r_blk+1)*4].T
                x_sub = a1_int8[c_blk*4:(c_blk+1)*4]
                act_mat[:, 0] = x_sub

                self.backend.write_wt_tile(w_tile)
                self.backend.write_act_tile(act_mat)
                self.backend.execute_op(OP_FC, 0)
                prod = np.dot(w_tile.astype(np.int32), x_sub.astype(np.int32))
                layer2_acc[r_blk*4:(r_blk+1)*4] += prod

        layer2_acc += self.b2.astype(np.int32)
        logits = layer2_acc[:self.num_classes]
        prediction = int(np.argmax(logits))
        return prediction, logits

    async def predict_image_async(self, image_16x16x3: np.ndarray) -> Tuple[int, np.ndarray]:
        """Runs full inference on a single 16x16x3 INT8 leaf image asynchronously on DUT via CocotbBackend."""
        assert isinstance(self.backend, CocotbBackend)
        x = image_16x16x3.flatten().astype(np.int8)

        n_in = 768
        n_hid = self.W1.shape[1]      # 64
        n_out = self.W2.shape[1]      # 4

        # Fast Layer 1: Outer c_blk, inner r_blk
        n_in_blks = n_in // 4    # 192
        n_hid_blks = n_hid // 4  # 16
        layer1_acc = np.zeros(n_hid, dtype=np.int32)
        act_mat = np.zeros((4, 4), dtype=np.int8)

        for c_blk in range(n_in_blks):
            x_sub = x[c_blk*4:(c_blk+1)*4]
            act_mat[:, 0] = x_sub

            await self.backend._pin_write(self.backend.dut, 0x4, BUF_ACT)
            for i in range(16):
                await self.backend._pin_write(self.backend.dut, 0x5, i)
                await self.backend._pin_write(self.backend.dut, 0x6, int(act_mat.flat[i]) & 0xFF)

            for r_blk in range(n_hid_blks):
                w_tile = self.W1[c_blk*4:(c_blk+1)*4, r_blk*4:(r_blk+1)*4].T

                await self.backend._pin_write(self.backend.dut, 0x4, BUF_WT)
                for i in range(16):
                    await self.backend._pin_write(self.backend.dut, 0x5, i)
                    await self.backend._pin_write(self.backend.dut, 0x6, int(w_tile.flat[i]) & 0xFF)

                await self.backend._pin_write(self.backend.dut, ADDR_CONFIG, 0)
                await self.backend._pin_write(self.backend.dut, ADDR_OPCODE, OP_FC)
                await self.backend._pin_write(self.backend.dut, ADDR_CONTROL, 0x01)
                await self.backend._wait_irq(self.backend.dut, timeout=80000)
                await self.backend._pin_write(self.backend.dut, ADDR_CONTROL, 0x04)

                prod = np.dot(w_tile.astype(np.int32), x_sub.astype(np.int32))
                layer1_acc[r_blk*4:(r_blk+1)*4] += prod

        layer1_acc += self.b1.astype(np.int32)
        a1_int8 = np.clip(layer1_acc >> 8, 0, 127).astype(np.int8)

        # Layer 2: 64 -> 4
        n_hid_blks2 = n_hid // 4  # 16
        n_out_blks = n_out // 4   # 1
        layer2_acc = np.zeros(n_out, dtype=np.int32)

        for c_blk in range(n_hid_blks2):
            x_sub = a1_int8[c_blk*4:(c_blk+1)*4]
            act_mat[:, 0] = x_sub

            await self.backend._pin_write(self.backend.dut, 0x4, BUF_ACT)
            for i in range(16):
                await self.backend._pin_write(self.backend.dut, 0x5, i)
                await self.backend._pin_write(self.backend.dut, 0x6, int(act_mat.flat[i]) & 0xFF)

            for r_blk in range(n_out_blks):
                w_tile = self.W2[c_blk*4:(c_blk+1)*4, r_blk*4:(r_blk+1)*4].T

                await self.backend._pin_write(self.backend.dut, 0x4, BUF_WT)
                for i in range(16):
                    await self.backend._pin_write(self.backend.dut, 0x5, i)
                    await self.backend._pin_write(self.backend.dut, 0x6, int(w_tile.flat[i]) & 0xFF)

                await self.backend._pin_write(self.backend.dut, ADDR_CONFIG, 0)
                await self.backend._pin_write(self.backend.dut, ADDR_OPCODE, OP_FC)
                await self.backend._pin_write(self.backend.dut, ADDR_CONTROL, 0x01)
                await self.backend._wait_irq(self.backend.dut, timeout=80000)
                await self.backend._pin_write(self.backend.dut, ADDR_CONTROL, 0x04)

                prod = np.dot(w_tile.astype(np.int32), x_sub.astype(np.int32))
                layer2_acc[r_blk*4:(r_blk+1)*4] += prod

        layer2_acc += self.b2.astype(np.int32)
        logits = layer2_acc[:self.num_classes]
        prediction = int(np.argmax(logits))
        return prediction, logits

    def compute_softmax_sync(self, logits: np.ndarray) -> np.ndarray:
        """
        Computes exact normalized infection probabilities using AI_BYTE OP_SOFTMAX EML block for 4 classes.
        """
        assert isinstance(self.backend, GoldenBackend)
        n = 4
        self.backend.chip.write_reg(ADDR_CONFIG, 0)
        self.backend.chip.write_reg(ADDR_SOFTMAX_N, n)

        # Scale logits to INT8 for EML hardware softmax
        z_scaled = np.clip(np.round(logits.astype(np.float32) / 100.0), -128, 127).astype(np.int8)
        for i in range(n):
            self.backend.chip.write_buf(BUF_ACT, i, int(z_scaled[i]) & 0xFF)

        self.backend.execute_op(OP_SOFTMAX, 0)
        res = self.backend.chip.result_bytes(n * 2)
        probs = np.zeros(n, dtype=np.float32)
        for i in range(n):
            raw_q88 = res[i * 2] | (res[i * 2 + 1] << 8)
            probs[i] = raw_q88 / 256.0
        return probs

    async def compute_softmax_async(self, logits: np.ndarray) -> np.ndarray:
        """
        Computes exact normalized infection probabilities using AI_BYTE OP_SOFTMAX EML block on DUT pins.
        """
        assert isinstance(self.backend, CocotbBackend)
        n = 4
        await self.backend._pin_write(self.backend.dut, ADDR_CONFIG, 0)
        await self.backend._pin_write(self.backend.dut, ADDR_SOFTMAX_N, n)

        z_scaled = np.clip(np.round(logits.astype(np.float32) / 100.0), -128, 127).astype(np.int8)
        for i in range(n):
            await self.backend._buf_write(self.backend.dut, BUF_ACT, i, int(z_scaled[i]) & 0xFF)

        await self.backend.execute_op(OP_SOFTMAX, 0)
        probs = np.zeros(n, dtype=np.float32)
        for i in range(n):
            b0 = await self.backend._buf_read(self.backend.dut, BUF_RES, i * 2)
            b1 = await self.backend._buf_read(self.backend.dut, BUF_RES, i * 2 + 1)
            raw_q88 = b0 | (b1 << 8)
            probs[i] = raw_q88 / 256.0
        return probs
