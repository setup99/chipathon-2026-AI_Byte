"""Cocotb tests for ai_byte_buffer_ctrl (cocotb unit tests)."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer


BUFFER_DEPTH = 256


def _i(signal, default=0):
    """int() that treats X/Z as default (needed at time 0 before reset)."""
    try:
        return int(signal.value)
    except ValueError:
        return default


async def reset_dut(dut, cycles=5):
    dut.rst_n.value = 0
    dut.soft_reset.value = 0
    dut.cpu_we.value = 0
    dut.cpu_re.value = 0
    dut.bc_start.value = 0
    dut.mode.value = 0
    dut.compute_unit.value = 0
    dut.addr_valid.value = 0
    dut.agu_done.value = 0
    dut.act_addr.value = 0
    dut.weight_addr.value = 0
    dut.result_addr.value = 0
    dut.cpu_buf_sel.value = 0
    dut.cpu_buf_addr.value = 0
    dut.cpu_wdata.value = 0
    dut.sram_act_rdata.value = 0
    dut.sram_wt_rdata.value = 0
    dut.sram_res_rdata.value = 0
    dut.result_data.value = 0
    dut.result_valid.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk)


async def sram_and_ce_model(dut, act_mem, wt_mem, res_mem):
    """Sync SRAM stubs + CE: result = act + weight (1 cycle later)."""
    while True:
        await RisingEdge(dut.clk)

        if _i(dut.rst_n) == 0:
            dut.result_valid.value = 0
            dut.result_data.value = 0
        else:
            av = _i(dut.act_valid)
            wv = _i(dut.weight_valid)
            dut.result_valid.value = 1 if (av and wv) else 0
            dut.result_data.value = (_i(dut.act_data) + _i(dut.weight_data)) & 0xFF

        if _i(dut.sram_act_ce):
            addr = _i(dut.sram_act_addr)
            if _i(dut.sram_act_we):
                act_mem[addr] = _i(dut.sram_act_wdata)
            else:
                dut.sram_act_rdata.value = act_mem[addr]

        if _i(dut.sram_wt_ce):
            addr = _i(dut.sram_wt_addr)
            if _i(dut.sram_wt_we):
                wt_mem[addr] = _i(dut.sram_wt_wdata)
            else:
                dut.sram_wt_rdata.value = wt_mem[addr]

        if _i(dut.sram_res_ce):
            addr = _i(dut.sram_res_addr)
            if _i(dut.sram_res_we):
                res_mem[addr] = _i(dut.sram_res_wdata)
            else:
                dut.sram_res_rdata.value = res_mem[addr]


async def cpu_write(dut, sel, addr, data):
    await FallingEdge(dut.clk)
    dut.mode.value = 0
    dut.cpu_buf_sel.value = sel
    dut.cpu_buf_addr.value = addr
    dut.cpu_wdata.value = data
    dut.cpu_we.value = 1
    dut.cpu_re.value = 0
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.cpu_we.value = 0
    await RisingEdge(dut.clk)


async def cpu_read(dut, sel, addr):
    await FallingEdge(dut.clk)
    dut.mode.value = 0
    dut.cpu_buf_sel.value = sel
    dut.cpu_buf_addr.value = addr
    dut.cpu_re.value = 1
    dut.cpu_we.value = 0
    await RisingEdge(dut.clk)  # issue CE
    await RisingEdge(dut.clk)  # rdata available
    data = int(dut.cpu_rdata.value)
    await FallingEdge(dut.clk)
    dut.cpu_re.value = 0
    await RisingEdge(dut.clk)
    return data


async def start_compute(dut):
    await FallingEdge(dut.clk)
    dut.mode.value = 1
    dut.compute_unit.value = 0
    dut.agu_done.value = 0
    dut.addr_valid.value = 0
    dut.bc_start.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.bc_start.value = 0


async def agu_send_addr(dut, a, w, r):
    while int(dut.agu_en.value) != 1:
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    while int(dut.addr_ready.value) == 0:
        dut.addr_valid.value = 0
        await FallingEdge(dut.clk)
    dut.act_addr.value = a
    dut.weight_addr.value = w
    dut.result_addr.value = r
    dut.addr_valid.value = 1
    await RisingEdge(dut.clk)  # fire
    await FallingEdge(dut.clk)
    dut.addr_valid.value = 0


async def agu_finish(dut):
    await FallingEdge(dut.clk)
    dut.addr_valid.value = 0
    dut.agu_done.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.agu_done.value = 0


async def pulse_soft_reset(dut):
    await FallingEdge(dut.clk)
    dut.soft_reset.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.soft_reset.value = 0
    await RisingEdge(dut.clk)


def _start_env(dut):
    act_mem = [0] * BUFFER_DEPTH
    wt_mem = [0] * BUFFER_DEPTH
    res_mem = [0] * BUFFER_DEPTH
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    cocotb.start_soon(sram_and_ce_model(dut, act_mem, wt_mem, res_mem))
    return act_mem, wt_mem, res_mem


@cocotb.test()
async def test_reset(dut):
    """Test 1: Reset."""
    _start_env(dut)
    await reset_dut(dut)
    assert int(dut.busy.value) == 0
    assert int(dut.done.value) == 0
    assert int(dut.error.value) == 0
    assert int(dut.act_ready.value) == 1
    assert int(dut.weight_ready.value) == 1
    assert int(dut.result_ready.value) == 1


@cocotb.test()
async def test_cpu_buffer_access(dut):
    """Test 2: CPU Buffer Access."""
    _start_env(dut)
    await reset_dut(dut)

    await cpu_write(dut, 0b00, 0, 0x12)
    await cpu_write(dut, 0b00, 1, 0x34)
    await cpu_write(dut, 0b01, 0, 0x03)
    await cpu_write(dut, 0b01, 1, 0x05)

    assert await cpu_read(dut, 0b00, 0) == 0x12
    assert await cpu_read(dut, 0b00, 1) == 0x34
    assert await cpu_read(dut, 0b01, 0) == 0x03
    assert await cpu_read(dut, 0b01, 1) == 0x05


@cocotb.test()
async def test_invalid_buffer_select(dut):
    """Test 3: Invalid BUFFER_SELECT."""
    _start_env(dut)
    await reset_dut(dut)

    await cpu_write(dut, 0b11, 0, 0xAA)
    assert int(dut.error.value) == 1
    await pulse_soft_reset(dut)
    assert int(dut.error.value) == 0


@cocotb.test()
async def test_compute_streaming(dut):
    """Test 4: Compute Streaming."""
    _, _, res_mem = _start_env(dut)
    await reset_dut(dut)

    await cpu_write(dut, 0b00, 0, 0x12)
    await cpu_write(dut, 0b00, 1, 0x34)
    await cpu_write(dut, 0b00, 2, 0x10)
    await cpu_write(dut, 0b00, 3, 0x20)
    await cpu_write(dut, 0b01, 0, 0x03)
    await cpu_write(dut, 0b01, 1, 0x05)
    await cpu_write(dut, 0b01, 2, 0x07)
    await cpu_write(dut, 0b01, 3, 0x09)

    await start_compute(dut)
    assert int(dut.busy.value) == 1
    assert int(dut.act_ready.value) == 0

    await agu_send_addr(dut, 0, 0, 0)
    await agu_send_addr(dut, 1, 1, 1)
    await agu_send_addr(dut, 2, 2, 2)
    await agu_send_addr(dut, 3, 3, 3)
    await agu_finish(dut)

    # Wait for done
    for _ in range(200):
        await RisingEdge(dut.clk)
        if int(dut.done.value) == 1:
            break
    else:
        assert False, "timeout waiting for done"

    assert int(dut.done.value) == 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    assert int(dut.busy.value) == 0

    assert res_mem[0] == (0x12 + 0x03) & 0xFF
    assert res_mem[1] == (0x34 + 0x05) & 0xFF
    assert res_mem[2] == (0x10 + 0x07) & 0xFF
    assert res_mem[3] == (0x20 + 0x09) & 0xFF
