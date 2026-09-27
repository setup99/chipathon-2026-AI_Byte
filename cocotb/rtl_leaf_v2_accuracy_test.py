"""
Cocotb test: runs N PlantVillage Leaf Disease v2 (4-Class Multi-Disease) images through RTL hardware
and saves results to JSON incrementally.
"""
import os, sys, json
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Timer
from cocotb.types import LogicArray
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "cocotb"))

from ai_byte_pads import buf_read, buf_write, pin_read, pin_write, wait_irq
from golden import *
from cnn_test_flow.leaf_driver_v2 import AiByteLeafRunnerV2
from cnn_test_flow.cnn_driver import CocotbBackend
from cnn_test_flow.leaf_model_v2 import load_leaf_model_v2
from cnn_test_flow.leaf_loader_v2 import get_leaf_dataset_v2, CLASS_NAMES

NUM_TEST = int(os.environ.get("RTL_NUM_TEST", "20"))


@cocotb.test()
async def test_rtl_leaf_v2_accuracy(dut):
    try:
        dut.input_PAD.value = 0
    except Exception:
        pass
    bits = ["z"] * 20
    for i in range(14):
        bits[i] = "0"
    dut.bidir_PAD.value = LogicArray("".join(reversed(bits)))
    cocotb.start_soon(Clock(dut.clk_PAD, 20, unit="ns").start())
    dut.rst_n_PAD.value = 0
    await Timer(200, unit="ns")
    dut.rst_n_PAD.value = 1
    await ClockCycles(dut.clk_PAD, 4)

    weights = load_leaf_model_v2()
    _, imgs_int8, lbls = get_leaf_dataset_v2("test")
    imgs = imgs_int8[:NUM_TEST]
    lbls = lbls[:NUM_TEST]

    hw_runner = AiByteLeafRunnerV2(CocotbBackend(dut), weights)
    results_path = REPO / "cnn_test_flow" / "leaf_v2_rtl_results.json"
    results = []
    correct = 0
    for idx in range(NUM_TEST):
        hw_pred, hw_logits = await hw_runner.predict_image_async(imgs[idx])
        is_corr = int(hw_pred) == int(lbls[idx])
        if is_corr:
            correct += 1
        results.append(dict(true=int(lbls[idx]), pred=int(hw_pred), logits=hw_logits.tolist()))
        status = "CORRECT" if is_corr else "WRONG"
        true_name = CLASS_NAMES[lbls[idx]]
        pred_name = CLASS_NAMES[hw_pred]
        cocotb.log.info(
            f"Image {idx+1}/{NUM_TEST}: True={true_name} ({lbls[idx]}), "
            f"HW_Pred={pred_name} ({hw_pred}) [{status}] "
            f"-> Running HW Accuracy: {correct}/{idx+1} ({correct/(idx+1)*100:.1f}%)"
        )
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2)
    cocotb.log.info(f"Completed! Saved {len(results)} Leaf Disease v2 results to {results_path}")
