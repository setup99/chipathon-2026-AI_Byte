"""
Cocotb test: runs N CIFAR-10 Airplane vs. Automobile images through the RTL hardware and saves results to JSON.
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
from cnn_test_flow.cifar_driver import AiByteCIFARRunner
from cnn_test_flow.cnn_driver import CocotbBackend
from cnn_test_flow.cifar_model import load_cifar_model, get_binary_cifar_dataset

NUM_TEST = int(os.environ.get("RTL_NUM_TEST", "20"))

@cocotb.test()
async def test_rtl_cifar_accuracy(dut):
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

    weights = load_cifar_model()
    # Load binary dataset: (raw, int8_16x16, labels)
    _, imgs_int8, lbls = get_binary_cifar_dataset("test")
    imgs = imgs_int8[:NUM_TEST]
    lbls = lbls[:NUM_TEST]

    hw_runner = AiByteCIFARRunner(CocotbBackend(dut), weights)
    results_path = REPO / "cnn_test_flow" / "cifar_rtl_results.json"
    results = []
    correct = 0
    for idx in range(NUM_TEST):
        hw_pred, hw_logits = await hw_runner.predict_image_async(imgs[idx])
        is_corr = int(hw_pred) == int(lbls[idx])
        if is_corr:
            correct += 1
        results.append(dict(true=int(lbls[idx]), pred=int(hw_pred), logits=hw_logits.tolist()))
        status = "CORRECT" if is_corr else "WRONG"
        cocotb.log.info(
            f"Image {idx+1}/{NUM_TEST}: True={lbls[idx]}, Pred={hw_pred} [{status}] "
            f"-> Running HW Accuracy: {correct}/{idx+1} ({correct/(idx+1)*100:.1f}%)"
        )
        with open(results_path, "w") as f:
            json.dump(results, f)
    cocotb.log.info(f"Completed! Saved {len(results)} CIFAR binary results to {results_path}")
