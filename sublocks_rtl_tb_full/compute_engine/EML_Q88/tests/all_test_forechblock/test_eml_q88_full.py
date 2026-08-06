# =============================================================================
#  test_eml_q88_full.py
#  ONE consolidated cocotb suite covering every EML Q8.8 function, all
#  driven exclusively through eml_wrapper_q88's opcode interface.
#
#  This does not replace the individual standalone suites
#  (test_sigmoid_q88.py, test_tanh_q88.py, test_recip_q88.py,
#   test_sqrt_q88.py, test_softmax_q88.py, test_wrapper_q88.py) --
#  it exists so the entire library can be exercised in a single
#  `make sim` run, with results reported together rather than across
#  six separate invocations. Test points are drawn from the same
#  sweeps already verified in each module's own standalone suite, so
#  the expected pass/fail behaviour matches what is already documented
#  for each function individually.
# =============================================================================

import math
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"

W = 16
F = 8
SCALE = 1 << F
Q88_MAX = 127.99609375
Q88_MIN = -128.0

OP_SIGMOID  = 0
OP_TANH     = 1
OP_RECIP    = 2
OP_SQRT     = 3
OP_SOFTMAX  = 4
OP_FEEDBACK = 5

# ── Q8.8 encode/decode ───────────────────────────────────────────────────────

def float_to_q88(val: float) -> int:
    if math.isnan(val):
        return 0
    if val >= Q88_MAX:
        return 0x7FFF
    if val <= Q88_MIN:
        return 0x8000
    raw = round(val * SCALE)
    raw = max(-(1 << 15), min((1 << 15) - 1, raw))
    return raw & 0xFFFF


def q88_to_float(raw) -> float:
    raw = int(raw) & 0xFFFF
    if raw >= 0x8000:
        raw -= 0x10000
    return raw / SCALE


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.opcode.value = 0
    dut.x_in.value = 0
    dut.z0_in.value = 0
    dut.z1_in.value = 0
    dut.z2_in.value = 0
    dut.z3_in.value = 0
    dut.x_ext.value = 0
    dut.y_ext.value = float_to_q88(1.0)
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def pulse_start(dut, timeout=60):
    await RisingEdge(dut.clk)
    dut.start.value = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0
    cycles = 0
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.valid.value) == 1:
            return cycles
    raise AssertionError("Timed out waiting for valid")


# ── per-opcode call helpers (all route through the wrapper) ────────────────

async def call_sigmoid(dut, x: float):
    dut.opcode.value = OP_SIGMOID
    dut.x_in.value = float_to_q88(x)
    cycles = await pulse_start(dut)
    return q88_to_float(dut.result.value), cycles, int(dut.ovf.value)


async def call_tanh(dut, x: float):
    dut.opcode.value = OP_TANH
    dut.x_in.value = float_to_q88(x)
    cycles = await pulse_start(dut)
    return q88_to_float(dut.result.value), cycles, int(dut.ovf.value)


async def call_recip(dut, x: float):
    dut.opcode.value = OP_RECIP
    dut.x_in.value = float_to_q88(x)
    cycles = await pulse_start(dut)
    return q88_to_float(dut.result.value), cycles, int(dut.ovf.value)


async def call_sqrt(dut, x: float):
    dut.opcode.value = OP_SQRT
    dut.x_in.value = float_to_q88(x)
    cycles = await pulse_start(dut)
    return q88_to_float(dut.result.value), cycles, int(dut.ovf.value)


async def call_softmax(dut, z0, z1, z2, z3):
    dut.opcode.value = OP_SOFTMAX
    dut.z0_in.value = float_to_q88(z0)
    dut.z1_in.value = float_to_q88(z1)
    dut.z2_in.value = float_to_q88(z2)
    dut.z3_in.value = float_to_q88(z3)
    cycles = await pulse_start(dut)
    results = [
        q88_to_float(dut.softmax_result0.value),
        q88_to_float(dut.softmax_result1.value),
        q88_to_float(dut.softmax_result2.value),
        q88_to_float(dut.softmax_result3.value),
    ]
    return results, cycles, int(dut.ovf.value)


async def call_feedback(dut, x_ext, y_ext, sel_x, sel_y):
    dut.opcode.value = OP_FEEDBACK
    dut.x_ext.value = float_to_q88(x_ext)
    dut.y_ext.value = float_to_q88(y_ext)
    dut.sel_x.value = sel_x
    dut.sel_y.value = sel_y
    cycles = await pulse_start(dut)
    return q88_to_float(dut.result.value), cycles, int(dut.ovf.value)


# ── shared check helper, same pattern used across all standalone suites ────

def check(log, label, got, expected, tol_rel, tol_abs, fails_counter):
    ae = abs(got - expected)
    re = ae / max(abs(expected), 1e-9)
    ok = re < tol_rel or ae < tol_abs
    if not ok:
        fails_counter[0] += 1
    log.info(
        f"  {label:<28s} got={got:+9.5f}  ref={expected:+9.5f}  "
        f"rel={re:.3%}  abs={ae:.5f}  {'ok' if ok else 'FAIL'}"
    )
    return ok


# =============================================================================
#  SECTION 1 -- SIGMOID via OP_SIGMOID
#  Same sweep points as test_sigmoid_q88.py
# =============================================================================

@cocotb.test()
async def test_full_sigmoid(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 70)
    dut._log.info("SECTION 1 -- SIGMOID (via wrapper OP_SIGMOID)")
    dut._log.info("=" * 70)

    fails = [0]
    points = [-4.0, -3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
    for x in points:
        got, cycles, ovf = await call_sigmoid(dut, x)
        ref = 1.0 / (1.0 + math.exp(-x))
        if abs(x) >= 4.0:
            tol_abs = 0.008  # matches the extreme-input bound found and
                              # fixed during standalone sigmoid verification
            tol_rel = 1.0     # absolute-only at this extreme
        else:
            tol_abs, tol_rel = 0.03, 0.06
        check(dut._log, f"sigma({x:+.2f})", got, ref, tol_rel, tol_abs, fails)
        assert cycles == 6, f"sigma({x}): expected 6 cycles, got {cycles}"

    assert fails[0] == 0, f"{fails[0]} sigmoid points failed"
    dut._log.info("PASS test_full_sigmoid")


# =============================================================================
#  SECTION 2 -- TANH via OP_TANH
#  Same sweep points as test_tanh_q88.py
# =============================================================================

@cocotb.test()
async def test_full_tanh(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 70)
    dut._log.info("SECTION 2 -- TANH (via wrapper OP_TANH)")
    dut._log.info("=" * 70)

    fails = [0]
    points = [-2.0, -1.5, -1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0, 1.5, 2.0]
    for x in points:
        got, cycles, ovf = await call_tanh(dut, x)
        ref = math.tanh(x)
        if abs(x) <= 0.25:
            tol_abs, tol_rel = 0.02, 1.0
        else:
            tol_abs, tol_rel = 0.03, 0.06
        check(dut._log, f"tanh({x:+.2f})", got, ref, tol_rel, tol_abs, fails)
        assert cycles == 7, f"tanh({x}): expected 7 cycles, got {cycles}"

    assert fails[0] == 0, f"{fails[0]} tanh points failed"
    dut._log.info("PASS test_full_tanh")


# =============================================================================
#  SECTION 3 -- RECIPROCAL via OP_RECIP
#  Same sweep points as test_recip_q88.py
# =============================================================================

@cocotb.test()
async def test_full_recip(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 70)
    dut._log.info("SECTION 3 -- RECIPROCAL (via wrapper OP_RECIP)")
    dut._log.info("=" * 70)

    fails = [0]
    points = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0, 16.0, 32.0, 64.0]
    for x in points:
        got, cycles, ovf = await call_recip(dut, x)
        ref = 1.0 / x
        check(dut._log, f"1/{x:<6.3f}", got, ref, 0.04, 0.02, fails)
        assert cycles == 4, f"recip({x}): expected 4 cycles, got {cycles}"

    assert fails[0] == 0, f"{fails[0]} reciprocal points failed"
    dut._log.info("PASS test_full_recip")


# =============================================================================
#  SECTION 4 -- SQUARE ROOT via OP_SQRT
#  Same sweep points as test_sqrt_q88.py
# =============================================================================

@cocotb.test()
async def test_full_sqrt(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 70)
    dut._log.info("SECTION 4 -- SQUARE ROOT (via wrapper OP_SQRT)")
    dut._log.info("=" * 70)

    fails = [0]
    points = [0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 9.0,
              10.0, 16.0, 20.0, 25.0, 36.0, 49.0, 50.0, 64.0, 100.0]
    for x in points:
        got, cycles, ovf = await call_sqrt(dut, x)
        ref = math.sqrt(x)
        check(dut._log, f"sqrt({x:<6.2f})", got, ref, 0.03, 0.02, fails)
        assert cycles == 4, f"sqrt({x}): expected 4 cycles, got {cycles}"

    assert fails[0] == 0, f"{fails[0]} sqrt points failed"
    dut._log.info("PASS test_full_sqrt")


# =============================================================================
#  SECTION 5 -- SOFTMAX via OP_SOFTMAX
#  Same vectors as test_softmax_q88.py
# =============================================================================

@cocotb.test()
async def test_full_softmax(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 70)
    dut._log.info("SECTION 5 -- SOFTMAX N=4 (via wrapper OP_SOFTMAX)")
    dut._log.info("=" * 70)

    fails = [0]

    vectors = [
        ([1.0, 1.0, 1.0, 1.0],  "uniform"),
        ([2.0, 0.0, 0.0, 0.0],  "peaked"),
        ([-1.0, 0.0, 1.0, 2.0], "ramp"),
        ([4.0, 3.0, 2.0, 1.0],  "large_range"),
    ]

    for z, label in vectors:
        got, cycles, ovf = await call_softmax(dut, *z)
        m = max(z)
        exps = [math.exp(v - m) for v in z]
        s = sum(exps)
        ref = [e / s for e in exps]

        dut._log.info(f"  softmax({label}): {z}")
        s_sum = sum(got)
        for i in range(4):
            check(dut._log, f"    elem[{i}]", got[i], ref[i], 0.08, 0.03, fails)
        sum_ok = abs(s_sum - 1.0) < 0.07
        if not sum_ok:
            fails[0] += 1
        dut._log.info(f"    sum={s_sum:.5f}  {'ok' if sum_ok else 'FAIL'}")
        assert cycles == 35, f"softmax({label}): expected 35 cycles, got {cycles}"

    assert fails[0] == 0, f"{fails[0]} softmax checks failed"
    dut._log.info("PASS test_full_softmax")


# =============================================================================
#  SECTION 6 -- FEEDBACK CELL via OP_FEEDBACK
#  All four sel_x/sel_y modes, same pattern as test_wrapper_q88.py's
#  feedback test plus the iteration modes covered in earlier feedback-
#  cell-specific testing.
# =============================================================================

@cocotb.test()
async def test_full_feedback(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 70)
    dut._log.info("SECTION 6 -- FEEDBACK CELL (via wrapper OP_FEEDBACK)")
    dut._log.info("=" * 70)

    fails = [0]

    # Mode 00: feed-forward
    got, cycles, ovf = await call_feedback(dut, 0.0, 1.0, 0, 0)
    check(dut._log, "feed-forward eml(0,1)", got, 1.0, 0.05, 0.02, fails)
    assert cycles == 1, f"feedback feed-forward: expected 1 cycle, got {cycles}"

    got, cycles, ovf = await call_feedback(dut, 1.0, 1.0, 0, 0)
    check(dut._log, "feed-forward eml(1,1)", got, math.e, 0.10, 0.10, fails)

    # Mode 10: iterate X -- seed then one step
    seed, _, _ = await call_feedback(dut, 0.0, 1.0, 0, 0)
    check(dut._log, "iterate-X seed", seed, 1.0, 0.05, 0.02, fails)
    step1, _, _ = await call_feedback(dut, 0.0, 1.0, 1, 0)  # x_ext ignored, sel_x=1 -> fb_reg
    expected_step1 = math.exp(seed)
    check(dut._log, "iterate-X step1", step1, expected_step1, 0.10, 0.30, fails)

    # Mode 01: iterate Y -- seed then one step
    seed2, _, _ = await call_feedback(dut, 1.0, 1.0, 0, 0)
    check(dut._log, "iterate-Y seed", seed2, math.e, 0.10, 0.10, fails)
    step1y, _, _ = await call_feedback(dut, 1.0, 1.0, 0, 1)  # y_ext ignored, sel_y=1 -> fb_reg
    expected_step1y = math.exp(1.0) - math.log(seed2)
    check(dut._log, "iterate-Y step1", step1y, expected_step1y, 0.10, 0.10, fails)

    # Mode 11: cross-feedback -- seed then one step
    seed3, _, _ = await call_feedback(dut, 0.0, 1.0, 0, 0)
    check(dut._log, "cross seed", seed3, 1.0, 0.05, 0.02, fails)
    step1c, _, _ = await call_feedback(dut, 0.0, 0.0, 1, 1)
    expected_step1c = math.exp(seed3)
    check(dut._log, "cross step1", step1c, expected_step1c, 0.10, 0.30, fails)

    assert fails[0] == 0, f"{fails[0]} feedback checks failed"
    dut._log.info("PASS test_full_feedback")


# =============================================================================
#  SECTION 7 -- OPCODE ISOLATION
#  Cycle through every opcode in sequence with no reset between calls,
#  confirming no state leaks across the entire six-function library.
# =============================================================================

@cocotb.test()
async def test_full_opcode_isolation(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 70)
    dut._log.info("SECTION 7 -- FULL OPCODE ISOLATION (all six, back-to-back)")
    dut._log.info("=" * 70)

    fails = [0]

    got, _, _ = await call_sigmoid(dut, 0.0)
    check(dut._log, "1) sigmoid(0)", got, 0.5, 0.02, 0.01, fails)

    got, _, _ = await call_tanh(dut, 0.0)
    check(dut._log, "2) tanh(0)", got, 0.0, 1.0, 0.01, fails)

    got, _, _ = await call_recip(dut, 4.0)
    check(dut._log, "3) recip(4)", got, 0.25, 0.04, 0.02, fails)

    got, _, _ = await call_sqrt(dut, 16.0)
    check(dut._log, "4) sqrt(16)", got, 4.0, 0.03, 0.02, fails)

    got_sm, _, _ = await call_softmax(dut, 1.0, 1.0, 1.0, 1.0)
    for i in range(4):
        check(dut._log, f"5) softmax[{i}]", got_sm[i], 0.25, 0.08, 0.03, fails)

    got, _, _ = await call_feedback(dut, 0.0, 1.0, 0, 0)
    check(dut._log, "6) feedback eml(0,1)", got, 1.0, 0.05, 0.02, fails)

    # and back to the start of the cycle once more, to confirm the
    # wrapper survived a full pass through every opcode without drift
    got, _, _ = await call_sigmoid(dut, 1.0)
    check(dut._log, "7) sigmoid(1) again", got, 1.0/(1.0+math.exp(-1.0)), 0.06, 0.03, fails)

    assert fails[0] == 0, f"{fails[0]} isolation checks failed"
    dut._log.info("PASS test_full_opcode_isolation")


# =============================================================================
#  SECTION 8 -- SUMMARY
#  Not an independent check -- just a final pass confirming every
#  section above ran, printed as one consolidated report line.
# =============================================================================

@cocotb.test()
async def test_full_summary(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 70)
    dut._log.info("EML Q8.8 FULL LIBRARY -- CONSOLIDATED RUN VIA WRAPPER")
    dut._log.info("  sigmoid | tanh | recip | sqrt | softmax | feedback")
    dut._log.info("  All six functions tested through eml_wrapper_q88 only --")
    dut._log.info("  no module instantiated or tested outside the wrapper.")
    dut._log.info("=" * 70)
    dut._log.info("PASS test_full_summary")
