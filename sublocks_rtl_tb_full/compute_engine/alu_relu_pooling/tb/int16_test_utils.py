"""
Shared helpers for the plain-INT16 cocotb testbenches.

Timing note: reading register outputs immediately after RisingEdge can
race with the DUT's own NBA update completing for that same edge (seen
in practice with this Icarus/VPI setup). The robust fix used throughout
these tests is to always land on FallingEdge (mid-cycle) before reading
any signal, and to only drive new inputs at that same safe mid-cycle
point. `tick()` bundles "advance one clock + settle" into one call.
"""
import cocotb
from cocotb.triggers import RisingEdge, FallingEdge

DEFAULT_TIMEOUT_TICKS = 40  # generous enough to cover the area-optimized ALU's
                            # ~20-cycle sequential multiply (vs. 2 cycles for add/sub)


async def tick(dut):
    """Advance one clock edge and land at a safe, settled mid-cycle point."""
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)


def signed_n(val, width):
    """Reinterpret the low `width` bits of val as a signed integer."""
    mask = (1 << width) - 1
    val &= mask
    sign_bit = 1 << (width - 1)
    if val & sign_bit:
        val -= (1 << width)
    return val


async def wait_for_valid(dut, timeout_ticks=DEFAULT_TIMEOUT_TICKS):
    """Tick until dut.valid is high, or raise after timeout_ticks."""
    for _ in range(timeout_ticks):
        if dut.valid.value == 1:
            return
        await tick(dut)
    raise TimeoutError(f"valid did not assert within {timeout_ticks} ticks")
