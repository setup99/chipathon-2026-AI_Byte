"""Cocotb tests for ai_byte_mmif (combinational decode + inout data)."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb.types import LogicArray


ADDR_CONTROL = 0x0
ADDR_STATUS = 0x1
ADDR_OPCODE = 0x2
ADDR_BUFFER_SELECT = 0x4
ADDR_BUFFER_ADDR = 0x5
ADDR_BUFFER_DATA = 0x6
ADDR_RESERVED = 0xC


def _i(signal, default=0):
    try:
        return int(signal.value)
    except ValueError:
        return default


def _hiz(width=8):
    return LogicArray("Z" * width)


async def release_data(dut):
    dut.data.value = _hiz()


async def reset_and_idle(dut):
    dut.rst_n.value = 0
    dut.addr.value = 0
    dut.we.value = 0
    dut.re.value = 0
    await release_data(dut)
    dut.irq_i.value = 0
    dut.reg_rdata.value = 0
    dut.buffer_select_i.value = 0
    dut.buffer_addr_i.value = 0
    dut.cpu_rdata.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_rf_write_decode(dut):
    """Non-BUFFER_DATA writes assert reg_we and forward addr/wdata."""
    Clock(dut.clk, 10, unit="ns").start()
    await reset_and_idle(dut)

    await RisingEdge(dut.clk)
    dut.addr.value = ADDR_OPCODE
    dut.we.value = 1
    dut.re.value = 0
    dut.data.value = 0xA5
    await Timer(1, unit="ns")

    assert _i(dut.reg_we) == 1
    assert _i(dut.reg_re) == 0
    assert _i(dut.cpu_we) == 0
    assert _i(dut.cpu_re) == 0
    assert _i(dut.reg_addr) == ADDR_OPCODE
    assert _i(dut.reg_wdata) == 0xA5

    await RisingEdge(dut.clk)
    dut.we.value = 0
    await release_data(dut)


@cocotb.test()
async def test_rf_read_decode(dut):
    """Non-BUFFER_DATA reads assert reg_re and drive data from reg_rdata."""
    Clock(dut.clk, 10, unit="ns").start()
    await reset_and_idle(dut)

    dut.reg_rdata.value = 0x3C
    dut.cpu_rdata.value = 0xFF

    await RisingEdge(dut.clk)
    dut.addr.value = ADDR_STATUS
    dut.we.value = 0
    dut.re.value = 1
    await release_data(dut)
    await Timer(1, unit="ns")

    assert _i(dut.reg_re) == 1
    assert _i(dut.reg_we) == 0
    assert _i(dut.cpu_re) == 0
    assert _i(dut.data) == 0x3C

    await RisingEdge(dut.clk)
    dut.re.value = 0


@cocotb.test()
async def test_buffer_data_write(dut):
    """addr=0x6 write routes to BC with BUFFER_SELECT / BUFFER_ADDR context."""
    Clock(dut.clk, 10, unit="ns").start()
    await reset_and_idle(dut)

    dut.buffer_select_i.value = 0x02  # Result
    dut.buffer_addr_i.value = 0x11

    await RisingEdge(dut.clk)
    dut.addr.value = ADDR_BUFFER_DATA
    dut.we.value = 1
    dut.re.value = 0
    dut.data.value = 0x77
    await Timer(1, unit="ns")

    assert _i(dut.reg_we) == 0
    assert _i(dut.reg_re) == 0
    assert _i(dut.cpu_we) == 1
    assert _i(dut.cpu_re) == 0
    assert _i(dut.cpu_buf_sel) == 0x2
    assert _i(dut.cpu_buf_addr) == 0x11
    assert _i(dut.cpu_wdata) == 0x77

    await RisingEdge(dut.clk)
    dut.we.value = 0
    await release_data(dut)


@cocotb.test()
async def test_buffer_data_read(dut):
    """addr=0x6 read routes from cpu_rdata onto data bus."""
    Clock(dut.clk, 10, unit="ns").start()
    await reset_and_idle(dut)

    dut.buffer_select_i.value = 0x00
    dut.buffer_addr_i.value = 0x05
    dut.reg_rdata.value = 0x00
    dut.cpu_rdata.value = 0xBE

    await RisingEdge(dut.clk)
    dut.addr.value = ADDR_BUFFER_DATA
    dut.we.value = 0
    dut.re.value = 1
    await release_data(dut)
    await Timer(1, unit="ns")

    assert _i(dut.cpu_re) == 1
    assert _i(dut.reg_re) == 0
    assert _i(dut.cpu_buf_sel) == 0x0
    assert _i(dut.cpu_buf_addr) == 0x05
    assert _i(dut.data) == 0xBE

    await RisingEdge(dut.clk)
    dut.re.value = 0


@cocotb.test()
async def test_data_hiz_when_idle(dut):
    """data is Hi-Z when re=0 (and when we=1)."""
    Clock(dut.clk, 10, unit="ns").start()
    await reset_and_idle(dut)

    dut.reg_rdata.value = 0xAA
    dut.cpu_rdata.value = 0xBB

    await RisingEdge(dut.clk)
    dut.addr.value = ADDR_OPCODE
    dut.we.value = 0
    dut.re.value = 0
    await release_data(dut)
    await Timer(1, unit="ns")
    assert "z" in str(dut.data.value).lower() or "Z" in str(dut.data.value)

    # Write cycle: MMIF must not drive
    dut.we.value = 1
    dut.data.value = 0x12
    await Timer(1, unit="ns")
    assert _i(dut.reg_we) == 1
    # Host is driving; MMIF drive_data is false
    assert _i(dut.reg_wdata) == 0x12

    dut.we.value = 0
    await release_data(dut)


@cocotb.test()
async def test_irq_passthrough(dut):
    """irq mirrors irq_i."""
    Clock(dut.clk, 10, unit="ns").start()
    await reset_and_idle(dut)

    dut.irq_i.value = 0
    await Timer(1, unit="ns")
    assert _i(dut.irq) == 0

    dut.irq_i.value = 1
    await Timer(1, unit="ns")
    assert _i(dut.irq) == 1


@cocotb.test()
async def test_reserved_addr_not_buffer(dut):
    """Reserved RF addresses never hit the BC path."""
    Clock(dut.clk, 10, unit="ns").start()
    await reset_and_idle(dut)

    dut.buffer_select_i.value = 0x1
    dut.buffer_addr_i.value = 0x22

    await RisingEdge(dut.clk)
    dut.addr.value = ADDR_RESERVED
    dut.we.value = 1
    dut.re.value = 0
    dut.data.value = 0x55
    await Timer(1, unit="ns")

    assert _i(dut.reg_we) == 1
    assert _i(dut.cpu_we) == 0

    await RisingEdge(dut.clk)
    dut.we.value = 0
    dut.re.value = 1
    await release_data(dut)
    dut.reg_rdata.value = 0x00
    await Timer(1, unit="ns")
    assert _i(dut.reg_re) == 1
    assert _i(dut.cpu_re) == 0

    await RisingEdge(dut.clk)
    dut.re.value = 0


@cocotb.test()
async def test_we_priority_over_re(dut):
    """If we and re both high, treat as write: no data drive, reg/cpu write path."""
    Clock(dut.clk, 10, unit="ns").start()
    await reset_and_idle(dut)

    dut.reg_rdata.value = 0xDE
    await RisingEdge(dut.clk)
    dut.addr.value = ADDR_CONTROL
    dut.we.value = 1
    dut.re.value = 1
    dut.data.value = 0x01
    await Timer(1, unit="ns")

    assert _i(dut.reg_we) == 1
    assert _i(dut.reg_re) == 1  # re still forwarded; RF may ignore
    # But data bus must not be driven by MMIF (write wins)
    # Host drives 0x01 — if MMIF also drove we'd contend; check drive_data off
    # by verifying we can still see host value
    assert _i(dut.data) == 0x01
    assert _i(dut.reg_wdata) == 0x01

    await RisingEdge(dut.clk)
    dut.we.value = 0
    dut.re.value = 0
    await release_data(dut)


@cocotb.test()
async def test_buffer_select_low_bits(dut):
    """Only buffer_select[1:0] appear on cpu_buf_sel."""
    Clock(dut.clk, 10, unit="ns").start()
    await reset_and_idle(dut)

    dut.buffer_select_i.value = 0xF3  # low bits = 3
    dut.buffer_addr_i.value = 0x00

    await RisingEdge(dut.clk)
    dut.addr.value = ADDR_BUFFER_DATA
    dut.we.value = 1
    dut.re.value = 0
    dut.data.value = 0x00
    await Timer(1, unit="ns")

    assert _i(dut.cpu_buf_sel) == 0x3

    await RisingEdge(dut.clk)
    dut.we.value = 0
    await release_data(dut)
