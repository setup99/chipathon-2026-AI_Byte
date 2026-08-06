# SPDX-FileCopyrightText: © 2025 Project Template Contributors / AI_BYTE 2026
# SPDX-License-Identifier: Apache-2.0

"""
Build + test entry for Chipathon chip_top with AI_BYTE core.

  SLOT=workshop make sim          # default runner modules: smoke + AI_BYTE tests
  COCOTB_TEST_MODULES=test_ai_byte SLOT=workshop make sim
"""

import os
import logging
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, ClockCycles
from cocotb_tools.runner import get_runner

sim = os.getenv("SIM", "icarus")
pdk_root = os.getenv("PDK_ROOT", str(Path(__file__).resolve().parent.parent / "gf180mcu"))
pdk = os.getenv("PDK", "gf180mcuD")
scl = os.getenv("SCL", "gf180mcu_fd_sc_mcu9t5v0")
gl = os.getenv("GL", "0") not in ("0", "false", "False", "")
slot = os.getenv("SLOT", "workshop")

hdl_toplevel = "chip_top"

PROJ = Path(__file__).resolve().parent
AI_BYTE_ROOT = PROJ / "../src/ai_byte"


def ai_byte_sources():
    """Return ordered list of AI_BYTE Verilog paths under src/ai_byte/."""
    order = [
        "post/alu_q88.v",
        "post/relu_int16.v",
        "post/pooling_int16.v",
        "post/scale_int16_to_int8.v",
        "post/block_wrapper.v",
        "eml/mitchell_log2_q88.v",
        "eml/mitchell_exp2_q88.v",
        "eml/eml_tile_q88.v",
        "eml/eml_sigmoid_q88_shared.v",
        "eml/eml_tanh_q88_shared.v",
        "eml/eml_recip_q88_shared.v",
        "eml/eml_sqrt_q88_shared.v",
        "eml/eml_softmax_q88_serial.v",
        "eml/eml_feedback_cell_q88_shared.v",
        "eml/eml_wrapper_q88_serial.v",
        "sa/ram_sdp.v",
        "sa/pe_gemv_ws.v",
        "sa/gemm_systolic_2d.v",
        "buffers/ai_byte_sram_buffer.v",
        "interface/ai_byte_mmif.v",
        "control/reg_file.v",
        "control/control_unit.v",
        "control/buffer_ctrl.v",
        "control/control_wrap.v",
        "top/ai_byte_core.v",
        "top/ai_byte_top.v",
    ]
    return [AI_BYTE_ROOT / p for p in order]


async def set_defaults(dut):
    try:
        w = len(dut.input_PAD)
    except TypeError:
        w = 1
    dut.input_PAD.value = 0


async def enable_power(dut):
    dut.VDD.value = 1
    dut.VSS.value = 0


async def start_clock(clock, freq=50):
    c = Clock(clock, 1 / freq * 1000, unit="ns")
    cocotb.start_soon(c.start())


async def reset(reset, active_low=True, time_ns=1000):
    cocotb.log.info("Reset asserted...")
    reset.value = not active_low
    await Timer(time_ns, unit="ns")
    reset.value = active_low
    cocotb.log.info("Reset deasserted.")


async def start_up(dut):
    await set_defaults(dut)
    if gl:
        await enable_power(dut)
    await start_clock(dut.clk_PAD)
    await reset(dut.rst_n_PAD)


@cocotb.test()
async def test_smoke_reset(dut):
    """Bring-up: reset completes, IRQ low after clear idle."""
    from cocotb.types import LogicArray

    await start_up(dut)
    # idle host
    bits = ["0"] * 14 + ["z"] * 6
    dut.bidir_PAD.value = LogicArray("".join(reversed(bits)))
    await ClockCycles(dut.clk_PAD, 20)
    raw = int(dut.bidir_PAD.value)
    irq = (raw >> 14) & 1
    assert irq == 0, f"IRQ unexpectedly high after reset (bidir={raw:#x})"
    cocotb.log.info("smoke reset OK")


def chip_top_runner():
    proj_path = Path(__file__).resolve().parent
    sources = []
    defines = {f"SLOT_{slot.upper()}": True}
    includes = [proj_path / "../src/"]

    if gl:
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / f"{scl}.v")
        sources.append(Path(pdk_root) / pdk / "libs.ref" / scl / "verilog" / "primitives.v")
        sources.append(proj_path / f"../final/pnl/{hdl_toplevel}.pnl.v")
        defines = {"FUNCTIONAL": True, "USE_POWER_PINS": True}
    else:
        sources.append(proj_path / "../src/chip_top.sv")
        sources.append(proj_path / "../src/chip_core.sv")
        sources.extend(ai_byte_sources())

    sources += [
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_io/verilog/gf180mcu_fd_io.v",
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_io/verilog/gf180mcu_ws_io.v",
        Path(pdk_root) / pdk / "libs.ref/gf180mcu_fd_ip_sram/verilog/gf180mcu_fd_ip_sram__sram512x8m8wm1.v",
        proj_path / "../ip/gf180mcu_ws_ip__id/vh/gf180mcu_ws_ip__id.v",
        proj_path / "../ip/gf180mcu_ws_ip__logo/vh/gf180mcu_ws_ip__logo.v",
    ]

    test_module = os.getenv("COCOTB_TEST_MODULES", "chip_top_tb,test_ai_byte")

    runner = get_runner(sim)
    runner.build(
        sources=[s for s in sources if Path(s).exists() or True],
        hdl_toplevel=hdl_toplevel,
        defines=defines,
        always=True,
        includes=includes,
        build_args=[],
        waves=True,
    )
    runner.test(
        hdl_toplevel=hdl_toplevel,
        test_module=test_module,
        waves=True,
    )


if __name__ == "__main__":
    chip_top_runner()
