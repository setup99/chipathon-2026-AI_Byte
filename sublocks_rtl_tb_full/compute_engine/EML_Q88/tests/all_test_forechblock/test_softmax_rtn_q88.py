# =============================================================================
#  test_softmax_rtn_q88.py
#  Proves eml_softmax_q88_rtn actually reconfigures N per-transaction on
#  ONE synthesized DUT instance -- issues several back-to-back calls with
#  different N each time, no reset between them, plus the invalid-N path.
# =============================================================================

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from eml_hw_model_q88 import q88, fq88
from eml_softmax_generic_model_q88 import eml_softmax

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"
W = 16
MAX_N = 8

Z_POOL = [1.0, 0.5, -0.5, -1.0, 2.0, 0.25, -2.0, 1.5]


def pack_z(zs):
    raw = 0
    for i, v in enumerate(zs):
        raw |= (q88(v) & ((1 << W) - 1)) << (i * W)
    return raw


def unpack_result(raw, n):
    mask = (1 << W) - 1
    return [fq88((raw >> (i * W)) & mask) for i in range(n)]


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.n_in.value = 0
    dut.z_in.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def run_call(dut, n, zs, timeout=120):
    dut.n_in.value = n
    dut.z_in.value = pack_z(zs)
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    cycles = 0
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.valid.value) == 1:
            raw = int(dut.result.value)
            return unpack_result(raw, n), cycles, int(dut.ovf.value), int(dut.n_err.value)
    raise AssertionError(f"Timed out waiting for valid (n={n}, z={zs})")


@cocotb.test()
async def test_rtn_changes_n_every_call(dut):
    """The actual capability being tested: one DUT instance, N changes on
    every single call, back-to-back, no reset in between."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    call_sequence = [3, 7, 2, 8, 4, 5, 6, 2, 8]
    fails = 0

    dut._log.info("=" * 78)
    dut._log.info("RUNTIME-N SOFTMAX: N changes every call, same DUT, no reset between")
    dut._log.info("=" * 78)

    for call_i, n in enumerate(call_sequence):
        zs = Z_POOL[:n]
        raws = [q88(v) for v in zs]

        got, cycles, rtl_ovf, n_err = await run_call(dut, n, zs)
        model_result, model_ovf = eml_softmax(raws, n)
        model_vals = [fq88(r) for r in model_result]

        expected_cycles = 8 * n + 3
        bitexact = all(abs(got[i] - model_vals[i]) < 1e-6 for i in range(n))
        s = sum(got)

        ok = bitexact and (cycles == expected_cycles) and (rtl_ovf == model_ovf) and (n_err == 0)
        if not ok:
            fails += 1

        dut._log.info(
            f"  call {call_i}: N={n}  cycles={cycles} (expect {expected_cycles})  "
            f"bit-exact={bitexact}  sum={s:.5f}  ovf={rtl_ovf}  n_err={n_err}  "
            f"{'ok' if ok else 'FAIL'}"
        )

    assert fails == 0, f"{fails}/{len(call_sequence)} calls failed"
    dut._log.info("PASS test_rtn_changes_n_every_call")


@cocotb.test()
async def test_rtn_stale_bits_cleared(dut):
    """After a large-N call, a following small-N call must not leak the
    previous call's higher-index result bits."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    # First: N=8, all slots get a nonzero-ish result
    await run_call(dut, 8, Z_POOL[:8])

    # Then: N=2 -- slots 2..7 of `result` must now read back as zero
    dut.n_in.value = 2
    dut.z_in.value = pack_z(Z_POOL[:2])
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    for _ in range(120):
        await RisingEdge(dut.clk)
        if int(dut.valid.value) == 1:
            break
    raw = int(dut.result.value)
    full = unpack_result(raw, MAX_N)
    dut._log.info(f"After N=8 then N=2: full 8-slot result bus = {[f'{v:.4f}' for v in full]}")
    stale = [v for v in full[2:] if v != 0.0]
    assert not stale, f"Stale high-index bits leaked from the previous N=8 call: {full[2:]}"
    dut._log.info("PASS test_rtn_stale_bits_cleared")


@cocotb.test()
async def test_rtn_invalid_n(dut):
    """n_in outside [2,8] must be rejected immediately, not silently run."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    for bad_n in [0, 1, 9, 15]:
        dut.n_in.value = bad_n
        dut.z_in.value = 0
        await RisingEdge(dut.clk)
        dut.start.value = 1
        await RisingEdge(dut.clk)
        dut.start.value = 0
        got_valid = False
        for _ in range(10):
            await RisingEdge(dut.clk)
            if int(dut.valid.value) == 1:
                got_valid = True
                break
        n_err = int(dut.n_err.value)
        ovf = int(dut.ovf.value)
        dut._log.info(f"  n_in={bad_n}: valid_within_10cyc={got_valid}  n_err={n_err}  ovf={ovf}")
        assert got_valid, f"n_in={bad_n} should reject immediately (within a few cycles), not hang"
        assert n_err == 1, f"n_in={bad_n} should set n_err=1"
        await ClockCycles(dut.clk, 3)

    dut._log.info("PASS test_rtn_invalid_n")
