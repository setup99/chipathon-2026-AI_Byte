"""Cocotb tests for ai_byte_buffers bank (via buffers_dut, DEPTH=16)."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

DEPTH = 16


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for prefix in ("act", "wt", "res"):
        getattr(dut, f"{prefix}_ce").value = 0
        getattr(dut, f"{prefix}_we").value = 0
        getattr(dut, f"{prefix}_addr").value = 0
        getattr(dut, f"{prefix}_wdata").value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)


async def buf_write(dut, which, addr, data):
    await FallingEdge(dut.clk)
    getattr(dut, f"{which}_addr").value = addr
    getattr(dut, f"{which}_wdata").value = data
    getattr(dut, f"{which}_we").value = 1
    getattr(dut, f"{which}_ce").value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    getattr(dut, f"{which}_ce").value = 0
    getattr(dut, f"{which}_we").value = 0


async def buf_read(dut, which, addr):
    await FallingEdge(dut.clk)
    getattr(dut, f"{which}_addr").value = addr
    getattr(dut, f"{which}_we").value = 0
    getattr(dut, f"{which}_ce").value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    data = int(getattr(dut, f"{which}_rdata").value)
    await FallingEdge(dut.clk)
    getattr(dut, f"{which}_ce").value = 0
    return data


@cocotb.test()
async def test_three_buffers_independent(dut):
    """Act / Weight / Result are separate memories."""
    await start_clock(dut)

    await buf_write(dut, "act", 0, 0xA1)
    await buf_write(dut, "wt", 0, 0xB2)
    await buf_write(dut, "res", 0, 0xC3)

    assert await buf_read(dut, "act", 0) == 0xA1
    assert await buf_read(dut, "wt", 0) == 0xB2
    assert await buf_read(dut, "res", 0) == 0xC3


@cocotb.test()
async def test_parallel_same_address(dut):
    """All three can be written same address without cross-talk."""
    await start_clock(dut)

    # Same cycle write to all three (posedge aligned)
    await FallingEdge(dut.clk)
    for which, data in (("act", 0x11), ("wt", 0x22), ("res", 0x33)):
        getattr(dut, f"{which}_addr").value = 4
        getattr(dut, f"{which}_wdata").value = data
        getattr(dut, f"{which}_we").value = 1
        getattr(dut, f"{which}_ce").value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    for which in ("act", "wt", "res"):
        getattr(dut, f"{which}_ce").value = 0
        getattr(dut, f"{which}_we").value = 0

    assert await buf_read(dut, "act", 4) == 0x11
    assert await buf_read(dut, "wt", 4) == 0x22
    assert await buf_read(dut, "res", 4) == 0x33


@cocotb.test()
async def test_bank_fill_unique_patterns(dut):
    """Each bank stores its own pattern across DEPTH."""
    await start_clock(dut)

    for addr in range(DEPTH):
        await buf_write(dut, "act", addr, (0x10 + addr) & 0xFF)
        await buf_write(dut, "wt", addr, (0x40 + addr) & 0xFF)
        await buf_write(dut, "res", addr, (0x80 + addr) & 0xFF)

    for addr in range(DEPTH):
        assert await buf_read(dut, "act", addr) == (0x10 + addr) & 0xFF
        assert await buf_read(dut, "wt", addr) == (0x40 + addr) & 0xFF
        assert await buf_read(dut, "res", addr) == (0x80 + addr) & 0xFF
