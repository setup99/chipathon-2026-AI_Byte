"""Cocotb tests for ai_byte_reg_file (cocotb unit tests)."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer


async def reset_dut(dut, cycles=4):
    dut.rst_n.value = 0
    dut.reg_addr.value = 0
    dut.reg_we.value = 0
    dut.reg_re.value = 0
    dut.reg_wdata.value = 0
    dut.status_i.value = 0
    dut.busy_i.value = 0
    dut.buffer_addr_inc.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk)


async def cpu_write(dut, addr, data):
    await FallingEdge(dut.clk)
    dut.reg_addr.value = addr
    dut.reg_wdata.value = data
    dut.reg_we.value = 1
    dut.reg_re.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.reg_we.value = 0


async def cpu_read(dut, addr):
    await FallingEdge(dut.clk)
    dut.reg_addr.value = addr
    dut.reg_re.value = 1
    dut.reg_we.value = 0
    await Timer(1, unit="ns")
    data = int(dut.reg_rdata.value)
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.reg_re.value = 0
    return data


@cocotb.test()
async def test_reset_defaults(dut):
    """Test 1: Reset / defaults."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    assert await cpu_read(dut, 0x0) == 0x00
    assert await cpu_read(dut, 0x2) == 0x00
    assert await cpu_read(dut, 0x3) == 0x00
    assert await cpu_read(dut, 0x4) == 0x00
    assert await cpu_read(dut, 0x5) == 0x00
    assert await cpu_read(dut, 0x7) == 0x00
    assert await cpu_read(dut, 0xF) == 0x01
    assert int(dut.opcode_o.value) == 0
    assert int(dut.buffer_addr_o.value) == 0


@cocotb.test()
async def test_rw_stored_registers(dut):
    """Test 2: R/W stored registers + broadcast."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    await cpu_write(dut, 0x2, 0xA5)
    assert await cpu_read(dut, 0x2) == 0x05
    assert int(dut.opcode_o.value) == 0x5

    await cpu_write(dut, 0x3, 0xFF)
    assert await cpu_read(dut, 0x3) == 0x3F
    assert int(dut.config_o.value) == 0x3F

    await cpu_write(dut, 0x4, 0x02)
    assert await cpu_read(dut, 0x4) == 0x02
    assert int(dut.buffer_select_o.value) == 0x02

    await cpu_write(dut, 0x5, 0x10)
    assert await cpu_read(dut, 0x5) == 0x10
    assert int(dut.buffer_addr_o.value) == 0x10

    await cpu_write(dut, 0x7, 0x1E)
    await cpu_write(dut, 0x8, 0x1F)
    await cpu_write(dut, 0x9, 0x03)
    await cpu_write(dut, 0xA, 0x10)
    assert int(dut.feature_rows_o.value) == 0x1E
    assert int(dut.feature_cols_o.value) == 0x1F
    assert int(dut.input_channels_o.value) == 0x03
    assert int(dut.output_channels_o.value) == 0x10
    assert await cpu_read(dut, 0x7) == 0x1E
    assert await cpu_read(dut, 0xA) == 0x10


@cocotb.test()
async def test_status_version_readonly(dut):
    """Test 3: STATUS mirror + VERSION RO."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    dut.status_i.value = 0b0000_0110
    assert await cpu_read(dut, 0x1) == 0x06

    await cpu_write(dut, 0x1, 0xFF)
    assert await cpu_read(dut, 0x1) == 0x06

    await cpu_write(dut, 0xF, 0x55)
    assert await cpu_read(dut, 0xF) == 0x01


@cocotb.test()
async def test_reserved_addresses(dut):
    """Test 4: Reserved addresses."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    await cpu_write(dut, 0x2, 0x05)
    await cpu_write(dut, 0xB, 0xAA)
    await cpu_write(dut, 0xC, 0xBB)
    await cpu_write(dut, 0xD, 0xCC)
    await cpu_write(dut, 0xE, 0xDD)
    assert await cpu_read(dut, 0xB) == 0x00
    assert await cpu_read(dut, 0xE) == 0x00
    assert await cpu_read(dut, 0x2) == 0x05


@cocotb.test()
async def test_control_pulses(dut):
    """Test 5: CONTROL side-effect pulses."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    # Preserve some regs for soft-reset check later
    await cpu_write(dut, 0x2, 0x05)
    await cpu_write(dut, 0x3, 0x3F)

    dut.busy_i.value = 0
    await FallingEdge(dut.clk)
    dut.reg_addr.value = 0x0
    dut.reg_wdata.value = 0x01  # START
    dut.reg_we.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.start_pulse.value) == 1
    await FallingEdge(dut.clk)
    dut.reg_we.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.start_pulse.value) == 0
    assert await cpu_read(dut, 0x0) == 0x00

    # START ignored when busy
    dut.busy_i.value = 1
    await FallingEdge(dut.clk)
    dut.reg_addr.value = 0x0
    dut.reg_wdata.value = 0x01
    dut.reg_we.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.start_pulse.value) == 0
    await FallingEdge(dut.clk)
    dut.reg_we.value = 0
    dut.busy_i.value = 0

    # SOFT_RESET + IRQ_CLEAR
    await FallingEdge(dut.clk)
    dut.reg_addr.value = 0x0
    dut.reg_wdata.value = 0x06
    dut.reg_we.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.soft_reset_pulse.value) == 1
    assert int(dut.irq_clear_pulse.value) == 1
    await FallingEdge(dut.clk)
    dut.reg_we.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.soft_reset_pulse.value) == 0
    assert int(dut.irq_clear_pulse.value) == 0

    assert await cpu_read(dut, 0x2) == 0x05
    assert await cpu_read(dut, 0x3) == 0x3F


@cocotb.test()
async def test_buffer_addr_inc(dut):
    """Test 6: BUFFER_ADDR auto-increment."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    await cpu_write(dut, 0x5, 0x20)
    await FallingEdge(dut.clk)
    dut.buffer_addr_inc.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.buffer_addr_inc.value = 0
    await RisingEdge(dut.clk)
    assert int(dut.buffer_addr_o.value) == 0x21
    assert await cpu_read(dut, 0x5) == 0x21

    # CPU write wins over inc
    await FallingEdge(dut.clk)
    dut.reg_addr.value = 0x5
    dut.reg_wdata.value = 0x55
    dut.reg_we.value = 1
    dut.buffer_addr_inc.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.reg_we.value = 0
    dut.buffer_addr_inc.value = 0
    await RisingEdge(dut.clk)
    assert int(dut.buffer_addr_o.value) == 0x55
