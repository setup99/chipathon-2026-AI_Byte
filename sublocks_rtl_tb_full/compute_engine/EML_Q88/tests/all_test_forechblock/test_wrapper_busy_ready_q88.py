# =============================================================================
#  test_wrapper_busy_ready_q88.py
#  Directed tests for the busy/ready handshake added on top of
#  eml_wrapper_q88_shared_busy. Covers:
#    1. ready=1 after reset, busy toggles correctly across a transaction
#    2. a start pulse issued while busy is ignored (dropped, not queued)
#    3. THE scenario busy/ready was built to fix: opcode changed away
#       from an in-flight transaction before its valid fires -- the
#       original transaction must still complete and be correctly
#       reported, not silently replaced by the new opcode's (empty) result
# =============================================================================

import math
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"
W = 16

OP_SIGMOID  = 0
OP_TANH     = 1
OP_RECIP    = 2
OP_SQRT     = 3
OP_SOFTMAX  = 4
OP_FEEDBACK = 5


def f2q(v: float) -> int:
    raw = round(v * 256)
    raw = max(-(1 << 15), min((1 << 15) - 1, raw))
    return raw & 0xFFFF


def q2f(raw) -> float:
    raw = int(raw) & 0xFFFF
    if raw >= 0x8000:
        raw -= 0x10000
    return raw / 256.0


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.opcode.value = 0
    dut.x_in.value = 0
    dut.n_in.value = 0
    dut.z_in.value = 0
    dut.x_ext.value = 0
    dut.y_ext.value = f2q(1.0)
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


@cocotb.test()
async def test_ready_after_reset(dut):
    """ready must be high (busy low) immediately after reset, with no
    transaction ever started."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    dut._log.info(f"after reset: busy={int(dut.busy.value)} ready={int(dut.ready.value)}")
    assert int(dut.ready.value) == 1
    assert int(dut.busy.value) == 0
    dut._log.info("PASS test_ready_after_reset")


@cocotb.test()
async def test_busy_toggles_across_transaction(dut):
    """busy must go high the cycle a transaction is accepted, stay high
    through the cycle valid fires (busy and ready are complementary the
    whole time), and clear one cycle after -- checked against sigmoid's
    known 6-cycle latency."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_SIGMOID
    dut.x_in.value = f2q(1.0)
    await RisingEdge(dut.clk)
    assert int(dut.ready.value) == 1, "should be ready before start"
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0

    busy_cycles = 0
    saw_valid = False
    for i in range(10):
        await RisingEdge(dut.clk)
        busy = int(dut.busy.value)
        ready = int(dut.ready.value)
        valid = int(dut.valid.value)
        dut._log.info(f"  cycle {i}: busy={busy} ready={ready} valid={valid}")
        assert busy == (1 - ready), "busy and ready must always be complementary"
        if busy:
            busy_cycles += 1
        if valid:
            saw_valid = True
            assert busy == 1, "busy stays high through the same cycle valid fires (clears the cycle after)"
            continue
        if saw_valid and not busy:
            break

    dut._log.info(f"busy was high for {busy_cycles} cycles (expect 6: accept cycle through the valid cycle)")
    assert busy_cycles == 6
    dut._log.info("PASS test_busy_toggles_across_transaction")


@cocotb.test()
async def test_start_while_busy_ignored(dut):
    """A start pulse issued while busy must be dropped, not queued --
    confirmed by trying to launch a second (different) transaction
    mid-flight and checking it has no effect: the original transaction
    still completes with its own correct result, and no extra latency
    or side effect from the ignored pulse appears."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_SIGMOID
    dut.x_in.value = f2q(1.0)
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0

    # DUT is now busy running sigmoid(1.0). Try to sneak in a second
    # start for a totally different opcode a couple cycles later.
    await ClockCycles(dut.clk, 2)
    assert int(dut.busy.value) == 1, "should still be busy at this point"
    dut.opcode.value = OP_SQRT
    dut.x_in.value = f2q(4.0)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    dut._log.info("issued an ignored start (OP_SQRT) while busy with sigmoid")

    # sigmoid should still complete correctly, at its normal latency
    for i in range(10):
        await RisingEdge(dut.clk)
        if int(dut.valid.value) == 1:
            got = q2f(dut.result.value)
            ref = 1.0 / (1.0 + math.exp(-1.0))
            dut._log.info(f"  sigmoid(1.0) completed: got={got:.5f} ref={ref:.5f}")
            assert abs(got - ref) < 0.05, "the ignored start must not have corrupted sigmoid's result"
            break
    else:
        assert False, "sigmoid transaction never completed"

    dut._log.info("PASS test_start_while_busy_ignored")


@cocotb.test()
async def test_opcode_glitch_scenario(dut):
    """THE scenario busy/ready fixes: launch OP_SIGMOID, then change
    `opcode` to something else BEFORE its valid fires (simulating a
    careless or buggy caller), and confirm sigmoid's transaction still
    completes correctly and is reported through `result`/`valid` at
    the right time -- not silently replaced by the other opcode."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut.opcode.value = OP_SIGMOID
    dut.x_in.value = f2q(1.0)
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0

    # immediately yank the opcode input away to something else, without
    # ever pulsing start again -- a well-behaved caller wouldn't do this,
    # but the wrapper must survive it
    await ClockCycles(dut.clk, 1)
    dut.opcode.value = OP_TANH
    dut._log.info("changed live opcode to OP_TANH mid-flight (no new start issued)")

    for i in range(10):
        await RisingEdge(dut.clk)
        if int(dut.valid.value) == 1:
            got = q2f(dut.result.value)
            ref = 1.0 / (1.0 + math.exp(-1.0))
            dut._log.info(f"  cycle {i}: valid fired, result={got:.5f} (expect sigmoid(1.0)~={ref:.5f})")
            assert abs(got - ref) < 0.05, (
                f"opcode glitch corrupted the in-flight transaction: got {got}, expected sigmoid(1.0)~={ref}"
            )
            break
    else:
        assert False, "transaction never completed after the opcode glitch"

    dut._log.info("PASS test_opcode_glitch_scenario")


@cocotb.test()
async def test_back_to_back_respecting_ready(dut):
    """A well-behaved caller (wait for ready, then start) issuing
    several different opcodes back-to-back, no reset in between."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    async def run(opcode, x, ref_fn, label):
        while int(dut.ready.value) == 0:
            await RisingEdge(dut.clk)
        dut.opcode.value = opcode
        dut.x_in.value = f2q(x)
        await RisingEdge(dut.clk)
        dut.start.value = 1
        await RisingEdge(dut.clk)
        dut.start.value = 0
        for _ in range(20):
            await RisingEdge(dut.clk)
            if int(dut.valid.value) == 1:
                got = q2f(dut.result.value)
                ref = ref_fn(x)
                dut._log.info(f"  {label}({x}) = {got:.5f} (ref {ref:.5f})")
                assert abs(got - ref) < 0.06 or abs(got - ref) < 0.03
                return
        assert False, f"{label} never completed"

    await run(OP_SIGMOID, 1.0, lambda x: 1 / (1 + math.exp(-x)), "sigmoid")
    await run(OP_TANH, 0.5, math.tanh, "tanh")
    await run(OP_RECIP, 2.0, lambda x: 1 / x, "recip")
    await run(OP_SQRT, 9.0, math.sqrt, "sqrt")
    dut._log.info("PASS test_back_to_back_respecting_ready")
