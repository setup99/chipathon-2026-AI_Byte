
import sys, os, json
from pathlib import Path

REPO = Path("/home/you/chipathon-2026-AI_Byte")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "cocotb"))
os.chdir(str(REPO))

os.environ["PDK_ROOT"] = os.environ.get("PDK_ROOT", str(Path.home() / ".cache/ai-byte/pdk/gf180mcu"))
os.environ["PDK"] = os.environ.get("PDK", "gf180mcuD")
os.environ["COCOTB_TEST_MODULES"] = "rtl_mnist_accuracy_test"

# Write a temporary cocotb test module
test_code = '''
import os, sys, json
from pathlib import Path
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Timer
from cocotb.types import LogicArray
import numpy as np

REPO = Path("/home/you/chipathon-2026-AI_Byte")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "cocotb"))

from ai_byte_pads import buf_read, buf_write, pin_read, pin_write, wait_irq
from golden import *
from cnn_test_flow.cnn_driver import AiByteCNNRunner, CocotbBackend, GoldenBackend
from cnn_test_flow.mnist_loader import get_test_dataset
from cnn_test_flow.model import load_model

@cocotb.test()
async def test_rtl_accuracy(dut):
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

    weights = load_model()
    imgs, lbls = get_test_dataset(10)
    hw_runner = AiByteCNNRunner(CocotbBackend(dut), weights)
    results = []
    for idx in range(10):
        hw_pred, hw_logits = await hw_runner.predict_image_async(imgs[idx])
        results.append({            "true": int(lbls[idx]),
            "pred": int(hw_pred),
            "logits": hw_logits.tolist()
        })
        cocotb.log.info(f"Image {idx}: true={lbls[idx]}, pred={hw_pred}")
    with open("/home/you/chipathon-2026-AI_Byte/cnn_test_flow/rtl_results.json", "w") as f:
        json.dump(results, f)
    cocotb.log.info(f"Saved {len(results)} results")
'''

with open(REPO / "cocotb" / "rtl_mnist_accuracy_test.py", "w") as f:
    f.write(test_code)

# Now run chip_top_tb.py which will pick up our test module
from cocotb.chip_top_tb import chip_top_runner
chip_top_runner()
