"""Cocotb unit tests for ai_byte_control_unit (compute-only FSM)."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer


async def reset_dut(dut, cycles=4):
    dut.rst_n.value = 0
    dut.start_pulse.value = 0
    dut.soft_reset.value = 0
    dut.irq_clear.value = 0
    dut.opcode_reg.value = 0
    dut.config_reg.value = 0
    dut.busy.value = 0
    dut.done.value = 0
    dut.error.value = 0
    dut.act_ready.value = 1
    dut.weight_ready.value = 1
    dut.result_ready.value = 1
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    dut.rst_n.value = 1
    for _ in range(2):
        await RisingEdge(dut.clk)


async def pulse(dut, signal, cycles=1):
    await FallingEdge(dut.clk)
    signal.value = 1
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    signal.value = 0


async def start_clock(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())


@cocotb.test()
async def test_reset_idle(dut):
    """Idle after reset: not busy/done/error, mode=0."""
    await start_clock(dut)
    await reset_dut(dut)
    assert int(dut.busy_o.value) == 0
    assert int(dut.done_o.value) == 0
    assert int(dut.error_o.value) == 0
    assert int(dut.irq.value) == 0
    assert int(dut.mode.value) == 0
    assert int(dut.bc_start.value) == 0
    assert int(dut.debug_state.value) == 0  # IDLE


@cocotb.test()
async def test_compute_done(dut):
    """START → ISSUE bc_start → EXEC wait done → DONE + irq."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.opcode_reg.value = 0x0  # CONV
    dut.config_reg.value = 0x1  # RELU_EN
    await pulse(dut, dut.start_pulse)

    # Advance until ISSUE (bc_start)
    for _ in range(10):
        await RisingEdge(dut.clk)
        if int(dut.bc_start.value) == 1:
            break
    else:
        assert False, "timeout waiting for bc_start"

    assert int(dut.mode.value) == 1
    assert int(dut.busy_o.value) == 1
    assert int(dut.compute_unit.value) == 0
    assert int(dut.relu_en.value) == 1

    # Stay in EXEC with busy
    await RisingEdge(dut.clk)
    dut.busy.value = 1
    dut.done.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
        assert int(dut.done_o.value) == 0

    # Complete
    await FallingEdge(dut.clk)
    dut.busy.value = 0
    dut.done.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)  # WBACK
    await RisingEdge(dut.clk)  # DONE
    await Timer(1, unit="ns")

    assert int(dut.done_o.value) == 1
    assert int(dut.error_o.value) == 0
    assert int(dut.irq.value) == 1
    assert int(dut.mode.value) == 0  # released for MMIF
    assert (int(dut.status_o.value) & 0x7) == 0b010  # DONE

    await pulse(dut, dut.irq_clear)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.done_o.value) == 0
    assert int(dut.irq.value) == 0
    assert int(dut.debug_state.value) == 0


@cocotb.test()
async def test_illegal_opcode_error(dut):
    """Illegal opcode 0x5 → ERROR + irq."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.opcode_reg.value = 0x5
    await pulse(dut, dut.start_pulse)

    for _ in range(10):
        await RisingEdge(dut.clk)
        if int(dut.error_o.value) == 1:
            break
    else:
        assert False, "timeout waiting for ERROR"

    assert int(dut.done_o.value) == 0
    assert int(dut.irq.value) == 1
    assert int(dut.bc_start.value) == 0
    assert (int(dut.status_o.value) & 0x7) == 0b001  # ERROR

    await pulse(dut, dut.irq_clear)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")
    assert int(dut.error_o.value) == 0
    assert int(dut.debug_state.value) == 0


@cocotb.test()
async def test_decode_polls_until_ready(dut):
    """DECODE waits while any *_ready is low, then issues."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.act_ready.value = 0
    dut.weight_ready.value = 1
    dut.result_ready.value = 1
    dut.opcode_reg.value = 0x1

    await pulse(dut, dut.start_pulse)

    # Should reach DECODE and stay (no bc_start)
    for _ in range(6):
        await RisingEdge(dut.clk)
    assert int(dut.bc_start.value) == 0
    assert int(dut.debug_state.value) == 2  # DECODE

    # Release ready → ISSUE
    await FallingEdge(dut.clk)
    dut.act_ready.value = 1
    for _ in range(4):
        await RisingEdge(dut.clk)
        if int(dut.bc_start.value) == 1:
            break
    else:
        assert False, "bc_start never asserted after ready"


@cocotb.test()
async def test_bc_error_path(dut):
    """BC error in EXEC → ERROR state."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.opcode_reg.value = 0x2
    await pulse(dut, dut.start_pulse)

    for _ in range(10):
        await RisingEdge(dut.clk)
        if int(dut.bc_start.value) == 1:
            break

    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.error.value = 1
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    assert int(dut.error_o.value) == 1
    assert int(dut.irq.value) == 1
    assert int(dut.done_o.value) == 0


@cocotb.test()
async def test_soft_reset_aborts(dut):
    """soft_reset returns FSM to IDLE and clears flags."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.opcode_reg.value = 0x0
    await pulse(dut, dut.start_pulse)
    for _ in range(4):
        await RisingEdge(dut.clk)

    await pulse(dut, dut.soft_reset)
    await RisingEdge(dut.clk)
    await Timer(1, unit="ns")

    assert int(dut.debug_state.value) == 0
    assert int(dut.busy_o.value) == 0
    assert int(dut.done_o.value) == 0
    assert int(dut.error_o.value) == 0
    assert int(dut.mode.value) == 0


@cocotb.test()
async def test_config_pipeline_enables(dut):
    """Latched CONFIG drives relu_en / pool_en / pool_type."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.opcode_reg.value = 0x0
    dut.config_reg.value = 0b0000_0111  # RELU + POOL + AVG
    await pulse(dut, dut.start_pulse)

    # After FETCH latch visible
    for _ in range(4):
        await RisingEdge(dut.clk)

    assert int(dut.relu_en.value) == 1
    assert int(dut.pool_en.value) == 1
    assert int(dut.pool_type.value) == 1
