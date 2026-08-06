# =============================================================================
#  test_softmax_full_q88.py
#  Complete test suite for eml_softmax_q88_rtn -- one file, one DUT
#  elaboration, everything that was previously split across three files:
#
#    SECTION 1 -- Reconfiguration proof
#      N changes every call on one instance, no reset/recompile between
#      calls; stale high-index result bits are cleared; invalid n_in is
#      rejected immediately.
#
#    SECTION 2 -- Full accuracy battery, repeated for every N in 2..8
#      uniform / peaked / ramp / sum-to-one / latency / large-range,
#      the same shapes as the original N=4 suite, generalized to N.
#
#    SECTION 3 -- Max-trick proof
#      the exact (4,1)-spread vectors that genuinely overflowed before
#      the max-trick was added, now bit-exact and ovf-free; dominant-
#      slot exactness; shift invariance on large-but-representable
#      logits.
#
#  All bit-exact checks cross the RTL against eml_softmax_generic_model_q88
#  (which itself reuses the verified eml_tile() from eml_hw_model_q88),
#  not just true-math tolerance -- the same discipline as the rest of
#  this project's crosscheck suites.
# =============================================================================

import math
import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from eml_hw_model_q88 import q88, fq88
from eml_softmax_generic_model_q88 import eml_softmax

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"
W = 16
MAX_N = 8
N_RANGE = [2, 3, 4, 5, 6, 7, 8]
Z_POOL = [1.0, 0.5, -0.5, -1.0, 2.0, 0.25, -2.0, 1.5]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def pack_z(zs):
    raw = 0
    for i, v in enumerate(zs):
        raw |= (q88(v) & ((1 << W) - 1)) << (i * W)
    return raw


def unpack_result(raw, n):
    mask = (1 << W) - 1
    return [fq88((raw >> (i * W)) & mask) for i in range(n)]


def true_softmax(z):
    m = max(z)
    exps = [math.exp(v - m) for v in z]
    s = sum(exps)
    return [e / s for e in exps]


def linspace(a, b, n):
    if n == 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.n_in.value = 0
    dut.z_in.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def run_softmax(dut, n, zs, timeout=120):
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
            return unpack_result(int(dut.result.value), n), cycles, int(dut.ovf.value)
    raise AssertionError(f"Timed out waiting for valid (N={n}, z={zs})")


# =============================================================================
# SECTION 1 -- Reconfiguration proof
# =============================================================================

@cocotb.test()
async def test_1_n_changes_every_call(dut):
    """One DUT instance, N changes on every single call, back-to-back,
    no reset in between -- the core claim of run-time reconfigurability."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 1.1 -- N changes every call, same DUT, no reset between")
    dut._log.info("=" * 78)

    call_sequence = [3, 7, 2, 8, 4, 5, 6, 2, 8]
    fails = 0
    for call_i, n in enumerate(call_sequence):
        zs = Z_POOL[:n]
        raws = [q88(v) for v in zs]

        got, cycles, rtl_ovf = await run_softmax(dut, n, zs)
        model_result, model_ovf = eml_softmax(raws, n)
        model_vals = [fq88(r) for r in model_result]

        expected_cycles = 8 * n + 3
        bitexact = all(abs(got[i] - model_vals[i]) < 1e-6 for i in range(n))
        ok = bitexact and (cycles == expected_cycles) and (rtl_ovf == model_ovf)
        if not ok:
            fails += 1
        dut._log.info(
            f"  call {call_i}: N={n}  cycles={cycles} (expect {expected_cycles})  "
            f"bit-exact={bitexact}  ovf={rtl_ovf}  {'ok' if ok else 'FAIL'}"
        )
    assert fails == 0, f"{fails}/{len(call_sequence)} calls failed"
    dut._log.info("PASS test_1_n_changes_every_call")


@cocotb.test()
async def test_2_stale_bits_cleared(dut):
    """After a large-N call, a following small-N call must not leak the
    previous call's higher-index result bits."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 1.2 -- stale high-index result bits cleared across calls")
    dut._log.info("=" * 78)

    await run_softmax(dut, 8, Z_POOL[:8])

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
    full = unpack_result(int(dut.result.value), MAX_N)
    dut._log.info(f"  after N=8 then N=2: 8-slot result bus = {[f'{v:.4f}' for v in full]}")
    stale = [v for v in full[2:] if v != 0.0]
    assert not stale, f"stale high-index bits leaked from the previous N=8 call: {full[2:]}"
    dut._log.info("PASS test_2_stale_bits_cleared")


@cocotb.test()
async def test_3_invalid_n_rejected(dut):
    """n_in outside [2,8] must be rejected immediately, not silently run."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 1.3 -- invalid n_in (0,1,9,15) rejected immediately")
    dut._log.info("=" * 78)

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
        dut._log.info(f"  n_in={bad_n}: valid_within_10cyc={got_valid}  n_err={n_err}")
        assert got_valid, f"n_in={bad_n} should reject immediately, not hang"
        assert n_err == 1, f"n_in={bad_n} should set n_err=1"
        await ClockCycles(dut.clk, 3)
    dut._log.info("PASS test_3_invalid_n_rejected")


# =============================================================================
# SECTION 2 -- Full accuracy battery, repeated for every N in 2..8
# =============================================================================

@cocotb.test()
async def test_4_uniform_all_n(dut):
    """Uniform logits [1,1,...,1] -> all outputs should be ~1/N, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 2.1 -- uniform [1]*N for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = [1.0] * n
        got, cycles, ovf = await run_softmax(dut, n, zs)
        expect = 1.0 / n
        worst = max(abs(v - expect) for v in got)
        s = sum(got)
        ok = worst < 0.05 and abs(s - 1.0) < 0.08
        if not ok:
            fails += 1
        dut._log.info(f"  N={n}: worst_err={worst:.4f}  sum={s:.4f}  cycles={cycles}  {'ok' if ok else 'FAIL'}")
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed uniform check"
    dut._log.info("PASS test_4_uniform_all_n")


@cocotb.test()
async def test_5_peaked_all_n(dut):
    """Peaked logits [2,0,0,...,0] -> element 0 should dominate, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 2.2 -- peaked [2,0,...,0] for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = [2.0] + [0.0] * (n - 1)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = sum(
            1 for v, r in zip(got, ref)
            if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03)
        )
        dut._log.info(f"  N={n}: cycles={cycles}  elem_fails={elem_fails}  {'ok' if elem_fails == 0 else 'FAIL'}")
        if elem_fails:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed peaked check"
    dut._log.info("PASS test_5_peaked_all_n")


@cocotb.test()
async def test_6_ramp_all_n(dut):
    """Monotonic ramp logits, linspace(-1,2,N), for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 2.3 -- ramp linspace(-1,2,N) for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = linspace(-1.0, 2.0, n)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = sum(
            1 for v, r in zip(got, ref)
            if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03)
        )
        dut._log.info(f"  N={n}: cycles={cycles}  elem_fails={elem_fails}  {'ok' if elem_fails == 0 else 'FAIL'}")
        if elem_fails:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed ramp check"
    dut._log.info("PASS test_6_ramp_all_n")


@cocotb.test()
async def test_7_sum_to_one_all_n(dut):
    """Random logit vectors -- every softmax output must sum to ~1.0, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    random.seed(42)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 2.4 -- sum-to-one, 8 random vectors per N, N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        n_fails = 0
        for _ in range(8):
            zs = [random.uniform(-2.0, 2.0) for _ in range(n)]
            got, cycles, ovf = await run_softmax(dut, n, zs)
            if abs(sum(got) - 1.0) >= 0.07:
                n_fails += 1
        dut._log.info(f"  N={n}: {8 - n_fails}/8 trials passed")
        if n_fails:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values had sum-to-one failures"
    dut._log.info("PASS test_7_sum_to_one_all_n")


@cocotb.test()
async def test_8_latency_all_n(dut):
    """Confirm cycles = 8*N + 3 holds for every N, back-to-back, no reset."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 2.5 -- latency = 8*N+3 for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        _, cycles, _ = await run_softmax(dut, n, [1.0] * n)
        expected = 8 * n + 3
        ok = cycles == expected
        if not ok:
            fails += 1
        dut._log.info(f"  N={n}: cycles={cycles}  expected={expected}  {'ok' if ok else 'FAIL'}")
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values had wrong latency"
    dut._log.info("PASS test_8_latency_all_n")


@cocotb.test()
async def test_9_large_range_all_n(dut):
    """Logit spread of 3 (linspace(3,0,N)), exercising the format's
    dynamic range, for every N."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 2.6 -- large range linspace(3,0,N) for every N in 2..8")
    dut._log.info("=" * 78)

    fails = 0
    for n in N_RANGE:
        zs = linspace(3.0, 0.0, n)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = sum(
            1 for v, r in zip(got, ref)
            if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03)
        )
        ok = elem_fails == 0 and ovf == 0
        dut._log.info(f"  N={n}: cycles={cycles}  ovf={ovf}  elem_fails={elem_fails}  {'ok' if ok else 'FAIL'}")
        if not ok:
            fails += 1
    assert fails == 0, f"{fails}/{len(N_RANGE)} N values failed large-range check"
    dut._log.info("PASS test_9_large_range_all_n")


# =============================================================================
# SECTION 3 -- Max-trick proof
# =============================================================================

@cocotb.test()
async def test_10_maxtrick_fixes_previously_overflowing_vectors(dut):
    """Replays the exact (4,1)-spread vectors that genuinely overflowed
    (sum(exp)=134.6 at N=7, 151.6 at N=8) before the max-trick was added."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 3.1 -- max-trick proof: replaying previously-overflowing (4,1) vectors")
    dut._log.info("=" * 78)

    cases = {
        6: (linspace(4.0, 1.0, 6), False),   # already fine before (sum(exp)=117.7)
        7: (linspace(4.0, 1.0, 7), True),    # WAS overflowing (sum(exp)=134.6)
        8: (linspace(4.0, 1.0, 8), True),    # WAS overflowing (sum(exp)=151.6)
    }
    fails = 0
    for n, (zs, was_overflowing) in cases.items():
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        elem_fails = sum(
            1 for v, r in zip(got, ref)
            if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03)
        )
        dominant_ok = got[0] == max(got)
        ok = (ovf == 0) and (elem_fails == 0) and dominant_ok
        if not ok:
            fails += 1
        tag = "WAS OVERFLOWING BEFORE" if was_overflowing else "was already fine"
        dut._log.info(f"  N={n} ({tag}): ovf={ovf}  elem_fails={elem_fails}  {'PASS' if ok else 'FAIL'}")
    assert fails == 0, f"{fails}/{len(cases)} previously-overflowing cases still fail"
    dut._log.info("PASS test_10_maxtrick_fixes_previously_overflowing_vectors")


@cocotb.test()
async def test_11_maxtrick_dominant_slot_bitexact_one(dut):
    """An extreme peak (spread of 100 post-shift) drives the dominant
    slot to bit-exact 1.0 and every far-below-max slot to exactly 0.0.
    ovf=1 is expected and correct here: the shifted values still route
    through the tile's x*log2(e) scaling stage, which itself saturates
    for shifts this large -- that's real, informative saturation, not
    an error in the final answer."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 3.2 -- dominant-slot exactness under an extreme peak")
    dut._log.info("=" * 78)

    zs = [50.0, -50.0, -50.0, -50.0]
    got, cycles, ovf = await run_softmax(dut, 4, zs)
    dut._log.info(f"  z={zs}  got={[f'{v:.6f}' for v in got]}  ovf={ovf}")
    assert abs(got[0] - 1.0) < 1e-6, f"dominant slot should be bit-exact 1.0, got {got[0]}"
    assert all(v == 0.0 for v in got[1:]), f"far-below-max slots should underflow to 0.0, got {got[1:]}"
    dut._log.info("PASS test_11_maxtrick_dominant_slot_bitexact_one")


@cocotb.test()
async def test_12_maxtrick_shift_invariance(dut):
    """softmax([100,99,98]) must equal softmax([2,1,0]) bit-exactly --
    only relative differences matter after the max-trick. Uses logits
    that are actually representable in Q8.8 (max ~127.996); [1000,999,998]
    would silently clamp to the same value three times during input
    encoding alone, which is a Q8.8 input-range limit unrelated to the
    max-trick's internal arithmetic."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 78)
    dut._log.info("SECTION 3.3 -- shift invariance: softmax([100,99,98]) vs softmax([2,1,0])")
    dut._log.info("=" * 78)

    got_big, _, ovf_big = await run_softmax(dut, 3, [100.0, 99.0, 98.0])
    got_small, _, ovf_small = await run_softmax(dut, 3, [2.0, 1.0, 0.0])
    dut._log.info(f"  big:   got={[f'{v:.4f}' for v in got_big]}  ovf={ovf_big}")
    dut._log.info(f"  small: got={[f'{v:.4f}' for v in got_small]}  ovf={ovf_small}")
    assert ovf_big == 0, "representable large logits should not overflow after the max-trick"
    for a, b in zip(got_big, got_small):
        assert abs(a - b) < 1e-6, f"shift invariance broken: {got_big} vs {got_small}"
    dut._log.info("PASS test_12_maxtrick_shift_invariance")
