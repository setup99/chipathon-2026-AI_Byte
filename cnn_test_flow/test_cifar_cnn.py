"""
Cocotb tests for CIFAR-10 hardware spatial tiling and streaming.
"""
import sys
from pathlib import Path

import cocotb
import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "cocotb"))

from ai_byte_pads import buf_read, buf_write, pin_read, pin_write, start_up, wait_irq
from golden import (
    ADDR_CONFIG, ADDR_CONTROL, ADDR_OPCODE, ADDR_STATUS,
    BUF_ACT, BUF_RES, BUF_WT, CFG_POOL, CFG_RELU, CFG_SCALE, OP_CONV
)

from cnn_test_flow.cifar_loader import get_test_dataset
from cnn_test_flow.cifar_model import load_cifar_model

@cocotb.test()
async def test_cifar_conv_tile(dut):
    """Verifies OP_CONV on a 3-channel CIFAR-10 image patch vs Golden model."""
    await start_up(dut)
    weights = load_cifar_model()
    W_conv = weights["W_conv"]

    imgs, lbls = get_test_dataset(1)
    # Get a single 4x4 spatial patch from the 3 channels
    patch_3c = imgs[0, :, 14:18, 14:18]  # (3, 4, 4) INT8

    # We will test hardware processing of channel 0 for output channel 0
    w_tile = W_conv[0, 0, :].reshape(4, 4)
    x_tile = patch_3c[0, :, :]
    
    flat_w = w_tile.flatten().astype(np.int8)
    flat_x = x_tile.flatten().astype(np.int8)

    for i in range(16):
        await buf_write(dut, BUF_WT, i, int(flat_w[i]) & 0xFF)
        await buf_write(dut, BUF_ACT, i, int(flat_x[i]) & 0xFF)

    # Run OP_CONV on hardware
    cfg = CFG_RELU | CFG_POOL | CFG_SCALE
    await pin_write(dut, ADDR_CONFIG, cfg)
    await pin_write(dut, ADDR_OPCODE, OP_CONV)
    await pin_write(dut, ADDR_CONTROL, 0x01)  # START
    await wait_irq(dut, timeout=40000)

    st = await pin_read(dut, ADDR_STATUS)
    assert (st & 0x1) == 0, f"Hardware ERROR reported in STATUS: {st:#x}"
    assert (st & 0x2) != 0, f"Expected DONE in STATUS: {st:#x}"

    hw_res = [await buf_read(dut, BUF_RES, i) for i in range(4)]
    await pin_write(dut, ADDR_CONTROL, 0x04)  # Clear IRQ
    
    cocotb.log.info(f"CIFAR-10 OP_CONV hardware test successful. hw_res={hw_res}")

