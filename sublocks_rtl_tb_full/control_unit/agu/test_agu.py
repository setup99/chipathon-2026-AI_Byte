"""Cocotb tests for ai_byte_agu V1 linear (cocotb unit tests)."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer


async def reset_dut(dut, cycles=4):
    dut.rst_n.value = 0
    dut.soft_reset.value = 0
    dut.agu_en.value = 0
    dut.addr_ready.value = 0
    dut.feature_cols_i.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk)


async def accept_beat(dut):
    """Accept one address beat (addr_ready high for the fire cycle)."""
    while int(dut.addr_valid.value) != 1:
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.addr_ready.value = 1
    idx = int(dut.act_addr.value)
    await RisingEdge(dut.clk)  # fire
    await Timer(1, unit="ns")
    await FallingEdge(dut.clk)
    dut.addr_ready.value = 0
    return idx


@cocotb.test()
async def test_reset_idle(dut):
    """Test 1: Reset idle."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)
    assert int(dut.addr_valid.value) == 0
    assert int(dut.agu_done.value) == 0


@cocotb.test()
async def test_n4_stream(dut):
    """Test 2: N=4 stream."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    dut.feature_cols_i.value = 4
    await FallingEdge(dut.clk)
    dut.agu_en.value = 1

    for i in range(4):
        got = await accept_beat(dut)
        assert got == i, f"beat {i}: got {got}"
        assert int(dut.act_addr.value) == int(dut.weight_addr.value)
        assert int(dut.weight_addr.value) == int(dut.result_addr.value)

    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.agu_done.value) == 1
    assert int(dut.addr_valid.value) == 0

    for _ in range(3):
        await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.agu_done.value) == 1

    await FallingEdge(dut.clk)
    dut.agu_en.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.agu_done.value) == 0
    assert int(dut.addr_valid.value) == 0


@cocotb.test()
async def test_backpressure(dut):
    """Test 3: Backpressure."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    dut.feature_cols_i.value = 3
    await FallingEdge(dut.clk)
    dut.agu_en.value = 1
    dut.addr_ready.value = 0

    while int(dut.addr_valid.value) != 1:
        await RisingEdge(dut.clk)
    for _ in range(5):
        await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.addr_valid.value) == 1
    assert int(dut.act_addr.value) == 0

    assert await accept_beat(dut) == 0
    assert await accept_beat(dut) == 1
    assert await accept_beat(dut) == 2

    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.agu_done.value) == 1

    await FallingEdge(dut.clk)
    dut.agu_en.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_n1(dut):
    """Test 4: N=1."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    dut.feature_cols_i.value = 1
    await FallingEdge(dut.clk)
    dut.agu_en.value = 1
    assert await accept_beat(dut) == 0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.agu_done.value) == 1
    await FallingEdge(dut.clk)
    dut.agu_en.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_n0_immediate_done(dut):
    """Test 5: N=0 immediate done."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    dut.feature_cols_i.value = 0
    await FallingEdge(dut.clk)
    dut.agu_en.value = 1
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.agu_done.value) == 1
    assert int(dut.addr_valid.value) == 0
    await FallingEdge(dut.clk)
    dut.agu_en.value = 0
    await RisingEdge(dut.clk)


@cocotb.test()
async def test_agu_en_drop_midstream(dut):
    """Test 6: agu_en drop mid-stream."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    await reset_dut(dut)

    dut.feature_cols_i.value = 8
    await FallingEdge(dut.clk)
    dut.agu_en.value = 1
    await accept_beat(dut)
    await accept_beat(dut)
    await FallingEdge(dut.clk)
    dut.agu_en.value = 0
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.addr_valid.value) == 0
    assert int(dut.agu_done.value) == 0
