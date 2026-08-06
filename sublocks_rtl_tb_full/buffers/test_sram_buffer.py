"""Cocotb tests for ai_byte_sram_buffer (via sram_buffer_dut, DEPTH=16)."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

# Must match hdl/sram_buffer_dut.v default DEPTH
DEPTH = 16


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.ce.value = 0
    dut.we.value = 0
    dut.addr.value = 0
    dut.wdata.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)


async def sram_write(dut, addr, data):
    await FallingEdge(dut.clk)
    dut.addr.value = addr
    dut.wdata.value = data
    dut.we.value = 1
    dut.ce.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.ce.value = 0
    dut.we.value = 0


async def sram_read(dut, addr):
    """Sync read: CE on cycle N, rdata valid after that posedge."""
    await FallingEdge(dut.clk)
    dut.addr.value = addr
    dut.we.value = 0
    dut.ce.value = 1
    await RisingEdge(dut.clk)  # capture into rdata
    await Timer(1, unit="ns")
    data = int(dut.rdata.value)
    await FallingEdge(dut.clk)
    dut.ce.value = 0
    return data


@cocotb.test()
async def test_reset_rdata_zero(dut):
    """Initial rdata is 0."""
    await start_clock(dut)
    assert int(dut.rdata.value) == 0


@cocotb.test()
async def test_write_readback(dut):
    """Write then read a few locations."""
    await start_clock(dut)

    pattern = [(0, 0x11), (1, 0x22), (7, 0xAB), (DEPTH - 1, 0xFF)]
    for addr, data in pattern:
        await sram_write(dut, addr, data)

    for addr, data in pattern:
        got = await sram_read(dut, addr)
        assert got == data, f"addr={addr}: got {got:#x} want {data:#x}"


@cocotb.test()
async def test_full_walking_pattern(dut):
    """Fill all DEPTH entries with addr-based pattern and verify."""
    await start_clock(dut)

    for addr in range(DEPTH):
        await sram_write(dut, addr, (addr * 3 + 5) & 0xFF)

    for addr in range(DEPTH):
        exp = (addr * 3 + 5) & 0xFF
        got = await sram_read(dut, addr)
        assert got == exp, f"addr={addr}: got {got:#x} want {exp:#x}"


@cocotb.test()
async def test_ce_low_no_write(dut):
    """Writes with ce=0 must not update memory."""
    await start_clock(dut)

    await sram_write(dut, 3, 0x55)
    assert await sram_read(dut, 3) == 0x55

    # Attempt write with ce held 0
    await FallingEdge(dut.clk)
    dut.addr.value = 3
    dut.wdata.value = 0x99
    dut.we.value = 1
    dut.ce.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.we.value = 0

    assert await sram_read(dut, 3) == 0x55


@cocotb.test()
async def test_ce_low_holds_rdata(dut):
    """When ce=0, rdata holds the last read value."""
    await start_clock(dut)

    await sram_write(dut, 2, 0x3C)
    got = await sram_read(dut, 2)
    assert got == 0x3C

    # Idle cycles with ce=0
    await FallingEdge(dut.clk)
    dut.ce.value = 0
    dut.we.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)
        await Timer(1, unit="ns")
        assert int(dut.rdata.value) == 0x3C


@cocotb.test()
async def test_overwrite(dut):
    """Last write to an address wins."""
    await start_clock(dut)

    await sram_write(dut, 5, 0x10)
    await sram_write(dut, 5, 0x20)
    assert await sram_read(dut, 5) == 0x20
