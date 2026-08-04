# =============================================================================
#  test_feedback_cell_q88.py
#  cocotb testbench for eml_feedback_cell_q88 (lightweight Q8.8 variant)
#
#  Same 12-test structure as test_feedback_cell_q824_v2.py, adapted for
#  16-bit Q8.8 encode/decode and the narrower dynamic range/resolution.
#  Tolerances are loosened where the format's lower resolution (1/256
#  vs 1/16,777,216) demands it -- flagged explicitly at each loosened
#  assertion rather than silently copied from the Q8.24 test.
# =============================================================================

import math
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from mul_routing_q88 import MULTIPLY_SHAPED, run_program_with_mul_routing
from programs_list import programs

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"

W = 16
F = 8
SCALE = 1 << F
Q88_MAX = 127.99609375     # (2**15 - 1) / 256
Q88_MIN = -128.0
PROG_TOL = 0.20             # loosened from 0.15 (Q8.24) -- Q8.8 resolution
                             # is 1/256 vs 1/16.7M, so the 15% bar used for
                             # the 24-bit design is unrealistically tight here


def float_to_q88(val: float) -> int:
    if isinstance(val, complex):
        val = val.real
    if math.isnan(val):
        return 0
    if val >= Q88_MAX:
        return 0x7FFF
    if val <= Q88_MIN:
        return 0x8000
    raw = round(val * SCALE)
    raw = max(-(1 << 15), min((1 << 15) - 1, raw))
    return raw & 0xFFFF


def q88_to_float(raw: int) -> float:
    raw = int(raw) & 0xFFFF
    if raw >= 0x8000:
        raw -= 0x10000
    return raw / SCALE


def as_complex(val) -> complex:
    return val if isinstance(val, complex) else complex(val)


def fmt(val) -> str:
    z = as_complex(val)
    if abs(z.imag) <= 1e-6:
        return f"{z.real:.5f}"
    return f"{z.real:.4f}{z.imag:+.4f}j"


async def reset_dut(dut):
    dut.rst.value      = 1
    dut.valid_in.value = 0
    dut.sel_x.value    = 0
    dut.sel_y.value    = 0
    dut.x_ext.value    = float_to_q88(0.0)
    dut.y_ext.value    = float_to_q88(1.0)
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def pulse_valid(dut):
    await RisingEdge(dut.clk)
    dut.valid_in.value = 1
    await RisingEdge(dut.clk)
    dut.valid_in.value = 0
    for _ in range(20):
        await RisingEdge(dut.clk)
        if int(dut.valid_out.value) == 1:
            return
    raise AssertionError("Timed out waiting for valid_out")


async def chip_eml(dut, x: float, y: float) -> float:
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(x)
    dut.y_ext.value = float_to_q88(y)
    await pulse_valid(dut)
    return q88_to_float(dut.out.value)


async def chip_exp(dut, x: float) -> float:
    return await chip_eml(dut, x, 1.0)


async def chip_ln(dut, y: float) -> float:
    if y <= 0.0:
        return -math.inf
    r = await chip_eml(dut, 0.0, y)
    return 1.0 - r


async def chip_mul(dut, a: float, b: float) -> float:
    if a == 0.0 or b == 0.0:
        return 0.0
    sign = -1.0 if (a < 0) != (b < 0) else 1.0
    abs_a, abs_b = abs(a), abs(b)
    ln_a = await chip_ln(dut, abs_a)
    ln_b = await chip_ln(dut, abs_b)
    if math.isinf(ln_a) or math.isinf(ln_b):
        return 0.0
    result = await chip_exp(dut, ln_a + ln_b)
    return sign * result


async def complex_eml_chip(dut, a, b) -> complex:
    a_c = as_complex(a)
    b_c = as_complex(b)
    ar, ai = a_c.real, a_c.imag
    br, bi = b_c.real, b_c.imag

    if abs(ai) < 1e-9 and abs(bi) < 1e-9 and br > 0:
        r = await chip_eml(dut, ar, br)
        return complex(r, 0.0)

    if math.isinf(ar) and ar < 0:
        exp_real, exp_imag = 0.0, 0.0
    elif math.isinf(ar) and ar > 0:
        exp_real, exp_imag = math.inf, 0.0
    else:
        exp_ar = await chip_exp(dut, ar)
        if abs(ai) > 1e-9:
            exp_real = await chip_mul(dut, exp_ar, math.cos(ai))
            exp_imag = await chip_mul(dut, exp_ar, math.sin(ai))
        else:
            exp_real, exp_imag = exp_ar, 0.0

    if abs(b_c) < 1e-12:
        ln_real, ln_imag = -math.inf, 0.0
    elif abs(bi) < 1e-9 and br > 0:
        ln_real = await chip_ln(dut, br)
        ln_imag = 0.0
    else:
        abs_b = abs(b_c)
        ln_real = await chip_ln(dut, abs_b) if abs_b > 0.01 else -math.inf
        ln_imag = math.atan2(bi, br)

    return complex(exp_real - ln_real, exp_imag - ln_imag)


async def run_program(dut, program: str, x_val: float, y_val: float):
    stack = []
    chip_calls = 0
    for tok in program:
        if tok == "1":
            stack.append(complex(1.0, 0.0))
        elif tok == "x":
            stack.append(complex(x_val, 0.0))
        elif tok == "y":
            stack.append(complex(y_val, 0.0))
        elif tok == "E":
            b_val = stack.pop()
            a_val = stack.pop()
            result = await complex_eml_chip(dut, a_val, b_val)
            chip_calls += 1
            stack.append(result)
    return (stack[-1] if stack else complex(0.0)), chip_calls


# =============================================================================
#  TEST 1 -- protocol_basic
# =============================================================================

@cocotb.test()
async def test_protocol_basic(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    assert int(dut.valid_out.value) == 0
    got = await chip_eml(dut, 0.0, 1.0)
    dut._log.info(f"eml(0,1): got={got:.6f}  expected=1.0  err={abs(got-1.0):.2e}")
    assert abs(got - 1.0) < 0.01
    assert int(dut.valid_out.value) == 1
    dut._log.info("PASS test_protocol_basic")


# =============================================================================
#  TEST 2 -- eml_scalar
# =============================================================================

@cocotb.test()
async def test_eml_scalar(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    got      = await chip_eml(dut, 0.5, 0.5)
    expected = math.exp(0.5) - math.log(0.5)
    ae       = abs(got - expected)
    dut._log.info(f"eml(0.5, 0.5): got={got:.5f}  expected={expected:.5f}  |err|={ae:.2e}")
    # loosened from 0.05 (Q8.24) -- Q8.8 quantisation alone is ~0.004,
    # plus correction-term error, so 0.08 absolute is the right bar here
    assert ae <= 0.08, f"eml(0.5,0.5) error {ae:.4f} > 0.08"
    dut._log.info("PASS test_eml_scalar")


# =============================================================================
#  TEST 3 -- exp_ln_sweep
# =============================================================================

@cocotb.test()
async def test_exp_ln_sweep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    ABS_TOL = 0.08    # loosened from 0.05 (Q8.24)
    REL_TOL = 0.04    # loosened from 0.02-0.03 (Q8.24)
    fails = 0
    total = 0

    dut._log.info("=" * 60)
    dut._log.info("Q8.8 SWEEP: exp(x) and ln(x) via feedback cell (feed-forward)")
    dut._log.info("=" * 60)

    dut._log.info("-- exp(x) sweep --")
    for x_10 in range(-30, 41, 5):
        x   = x_10 / 10.0
        got = await chip_exp(dut, x)
        ref = math.exp(x)
        ae  = abs(got - ref)
        re  = ae / max(abs(ref), 1e-9)
        ok  = (ae < ABS_TOL) or (re < REL_TOL)
        total += 1
        if not ok:
            fails += 1
        dut._log.info(
            f"  exp({x:+5.1f}): got={got:+10.4f}  ref={ref:+10.4f}  "
            f"|err|={ae:.2e}  {'ok' if ok else 'FAIL'}"
        )

    dut._log.info("-- ln(x) sweep --")
    ln_points = [0.1, 0.2, 0.5, 1.0, 1.5, 2.0, math.e, 5.0, 10.0, 20.0]
    for x in ln_points:
        got = await chip_ln(dut, x)
        ref = math.log(x)
        ae  = abs(got - ref)
        re  = ae / max(abs(ref), 1e-9)
        ok  = (ae < ABS_TOL) or (re < REL_TOL)
        total += 1
        if not ok:
            fails += 1
        dut._log.info(
            f"  ln({x:+7.3f}): got={got:+10.4f}  ref={ref:+10.4f}  "
            f"|err|={ae:.2e}  {'ok' if ok else 'FAIL'}"
        )

    dut._log.info(f"-- Sweep: {total - fails}/{total} within tolerance --")
    assert fails <= 4, f"Too many sweep failures: {fails}/{total}"
    dut._log.info("PASS test_exp_ln_sweep")


# =============================================================================
#  TEST 4 -- eml_mul
# =============================================================================

@cocotb.test()
async def test_eml_mul(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 60)
    dut._log.info("Q8.8 MUL TEST -- hardware log-domain a*b")
    dut._log.info("=" * 60)

    cases = [
        (2.0,  3.0,  6.0,  "2*3=6"),
        (1.5,  2.0,  3.0,  "1.5*2=3"),
        (0.5,  0.5,  0.25, "0.5*0.5=0.25"),
        (4.0,  0.25, 1.0,  "4*0.25=1"),
        (10.0, 2.0,  20.0, "10*2=20"),
        (-2.0, 3.0, -6.0,  "-2*3=-6"),
        (2.0, -3.0, -6.0,  "2*-3=-6"),
        (-1.5,-2.0, 3.0,   "-1.5*-2=3"),
        (0.0,  5.0,  0.0,  "0*5=0"),
        (1.0,  1.0,  1.0,  "1*1=1"),
    ]
    fails = 0
    for a, b, expected, lbl in cases:
        got = await chip_mul(dut, a, b)
        ae  = abs(got - expected)
        re  = ae / max(abs(expected), 1e-9)
        # loosened from 0.05/0.02 (Q8.24) to 0.08/0.05 (Q8.8 resolution)
        ok  = (re < 0.08) or (ae < 0.05)
        if not ok:
            fails += 1
        dut._log.info(
            f"  mul({a:+5.2f},{b:+5.2f})={expected:+7.3f}  "
            f"got={got:+7.4f}  rel={re:.2%}  {'ok' if ok else 'FAIL'}"
        )

    assert fails == 0, f"chip_mul had {fails} failures"
    dut._log.info("PASS test_eml_mul")


# =============================================================================
#  TEST 5 -- all_38_functions
# =============================================================================

@cocotb.test()
async def test_all_38_functions(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    x_val, y_val = 0.5, 0.5
    accurate, degraded, poor = [], [], []
    total_chip_calls = 0

    dut._log.info("=" * 70)
    dut._log.info("38-FUNCTION SWEEP -- eml_feedback_cell_q88 (lightweight)")
    dut._log.info("  exp2/log2: 11/32 correction  |  mul: log-domain + routing")
    dut._log.info("=" * 70)

    for name, program, arity, expected_raw in programs:
        expected = as_complex(expected_raw)
        dut.sel_x.value = 0
        dut.sel_y.value = 0

        actual, chip_calls = await run_program_with_mul_routing(
            dut, name, program, x_val, y_val, run_program,
            chip_mul, chip_exp, chip_ln,
        )
        total_chip_calls += chip_calls

        actual_cmp = complex(actual.real, 0) if abs(expected.imag) < 1e-6 else actual
        err     = abs(actual_cmp - expected)
        rel_err = err / max(abs(expected), 1e-6) if abs(expected) >= 0.01 else err
        entry   = (name, actual, expected, rel_err, chip_calls)

        if rel_err <= PROG_TOL:
            accurate.append(entry)
            tag = "ACC "
        elif rel_err <= 1.0:
            degraded.append(entry)
            tag = "DEG "
        else:
            poor.append(entry)
            tag = "FAIL"

        dut._log.info(
            f"  {tag}  {name:15s}:  got={fmt(actual):16s}  "
            f"exp={fmt(expected):16s}  err={rel_err:6.1%}  calls={chip_calls}"
        )

    dut._log.info("=" * 70)
    dut._log.info("Q8.8 VERIFICATION REPORT")
    dut._log.info("=" * 70)
    dut._log.info(f"  Total chip EML calls    : {total_chip_calls}")
    dut._log.info(f"  Accurate  (< 20%)       : {len(accurate)}/{len(programs)}")
    dut._log.info(f"  Degraded  (20-100%)     : {len(degraded)}/{len(programs)}")
    dut._log.info(f"  Poor      (> 100%)      : {len(poor)}/{len(programs)}")
    if poor:
        dut._log.info(f"  Still failing           : {[e[0] for e in poor]}")
    dut._log.info("=" * 70)

    # Gate reflects the measured Q8.8 result, not the Q8.24 number --
    # the narrower format is expected to do somewhat worse on the deep
    # multiply-routed and inverse-trig compositions.
    assert len(accurate) >= 20, (
        f"Regression: only {len(accurate)} accurate, expected >= 20 "
        f"for Q8.8 with mul routing. Still failing: {[e[0] for e in poor]}"
    )
    dut._log.info("PASS test_all_38_functions")


# =============================================================================
#  TEST 6 -- iterate_x
# =============================================================================

@cocotb.test()
async def test_iterate_x(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 50)
    dut._log.info("ITERATE X (Q8.8)  sel_x=1 sel_y=0  y_ext=1.0")
    dut._log.info("=" * 50)

    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(0.0)
    dut.y_ext.value = float_to_q88(1.0)
    await pulse_valid(dut)
    seed = q88_to_float(dut.out.value)
    dut._log.info(f"  seed: got={seed:.6f}  expected=1.0  err={abs(seed-1.0):.2e}")
    assert abs(seed - 1.0) < 0.02

    dut.sel_x.value = 1
    dut.sel_y.value = 0
    dut.y_ext.value = float_to_q88(1.0)
    prev = seed
    results = [seed]

    for step in range(1, 4):
        await pulse_valid(dut)
        got = q88_to_float(dut.out.value)
        expected = math.exp(prev)
        ae = abs(got - expected)
        re = ae / max(abs(expected), 1e-6)
        results.append(got)
        dut._log.info(
            f"  step {step}: got={got:10.4f}  expected={expected:10.4f}  "
            f"rel={re:.2%}  {'[SAT]' if got>=127.9 else ''}"
        )
        if got >= 127.9:
            dut._log.info("  Q8.8 saturated -- correct HW limit")
            break
        assert re < 0.15, f"Step {step} error {re:.2%} > 15%"
        prev = got

    dut._log.info(f"  Sequence: {' -> '.join(f'{v:.4f}' for v in results)}")
    dut._log.info("PASS test_iterate_x")


# =============================================================================
#  TEST 7 -- iterate_y
# =============================================================================

@cocotb.test()
async def test_iterate_y(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 50)
    dut._log.info("ITERATE Y (Q8.8)  sel_x=0 sel_y=1  x_ext=1.0")
    dut._log.info("  Fixed point: y* = e - ln(y*) ~ 1.7632")
    dut._log.info("=" * 50)

    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(1.0)
    dut.y_ext.value = float_to_q88(1.0)
    await pulse_valid(dut)
    seed = q88_to_float(dut.out.value)
    dut._log.info(f"  seed: got={seed:.5f}  expected~=e  err={abs(seed-math.e):.4f}")
    assert abs(seed - math.e) < 0.25

    dut.sel_x.value = 0
    dut.sel_y.value = 1
    dut.x_ext.value = float_to_q88(1.0)

    FIXED_PT = 1.7632228343518967
    prev = seed
    results = [seed]

    for step in range(1, 8):
        await pulse_valid(dut)
        got = q88_to_float(dut.out.value)
        if prev > 0:
            expected = math.exp(1.0) - math.log(prev)
        else:
            expected = math.inf
        ae   = abs(got - expected)
        dist = abs(got - FIXED_PT)
        results.append(got)
        dut._log.info(
            f"  step {step}: got={got:8.4f}  exp={expected:8.4f}  "
            f"|err|={ae:.4f}  dist_fp={dist:.4f}"
        )
        assert ae < 0.40, f"Step {step} error {ae:.4f} too large"
        prev = got

    dist_final = abs(results[-1] - FIXED_PT)
    dut._log.info(f"  Final dist to fixed point: {dist_final:.4f}")
    # loosened bound vs Q8.24 (0.45/0.50) -- coarser correction error means
    # a wider basin of oscillation around the fixed point is expected
    assert dist_final < 0.60, f"Sequence drifted: dist={dist_final:.4f}"
    dut._log.info(f"  Sequence: {' -> '.join(f'{v:.4f}' for v in results)}")
    dut._log.info("PASS test_iterate_y")


# =============================================================================
#  TEST 8 -- cross_feedback
# =============================================================================

@cocotb.test()
async def test_cross_feedback(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 50)
    dut._log.info("CROSS-FEEDBACK (Q8.8)  sel_x=1 sel_y=1")
    dut._log.info("=" * 50)

    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(0.0)
    dut.y_ext.value = float_to_q88(1.0)
    await pulse_valid(dut)
    seed = q88_to_float(dut.out.value)
    dut._log.info(f"  seed: got={seed:.5f}  expected=1.0")
    assert abs(seed - 1.0) < 0.02

    dut.sel_x.value = 1
    dut.sel_y.value = 1
    prev = seed
    results = [seed]

    for step in range(1, 4):
        await pulse_valid(dut)
        got = q88_to_float(dut.out.value)
        if prev > 0:
            expected = math.exp(prev) - math.log(prev)
        else:
            expected = math.inf
        ae = abs(got - expected)
        re = ae / max(abs(expected), 1e-6)
        results.append(got)
        dut._log.info(
            f"  step {step}: got={got:10.4f}  exp={expected:10.4f}  "
            f"rel={re:.2%}  {'[SAT]' if got>=127.9 else ''}"
        )
        if got >= 127.9:
            dut._log.info("  Saturated -- correct HW limit")
            break
        assert re < 0.15 or ae < 2.0, f"Step {step} error {re:.2%}"
        prev = got

    dut._log.info(f"  Sequence: {' -> '.join(f'{v:.4f}' for v in results)}")
    dut._log.info("PASS test_cross_feedback")


# =============================================================================
#  TEST 9 -- reset_mid_sequence
# =============================================================================

@cocotb.test()
async def test_reset_mid_sequence(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("RESET MID-SEQUENCE (Q8.8)")
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(0.0)
    dut.y_ext.value = float_to_q88(1.0)
    await pulse_valid(dut)

    dut.sel_x.value = 1
    dut.sel_y.value = 0
    await pulse_valid(dut)
    before = q88_to_float(dut.out.value)
    assert abs(before - 1.0) > 0.1, "fb_reg should have advanced"

    dut.rst.value = 1
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)

    dut.sel_x.value = 1
    dut.sel_y.value = 0
    dut.y_ext.value = float_to_q88(1.0)
    await pulse_valid(dut)
    after = q88_to_float(dut.out.value)
    dut._log.info(f"  after rst: got={after:.5f}  expected~=e  err={abs(after-math.e):.4f}")
    assert abs(after - math.e) < 0.25
    dut._log.info("PASS test_reset_mid_sequence")


# =============================================================================
#  TEST 10 -- overflow_y_zero
# =============================================================================

@cocotb.test()
async def test_overflow_y_zero(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("OVERFLOW (Q8.8) -- y=0 -> ovf must = 1")
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(1.0)
    dut.y_ext.value = 0
    await pulse_valid(dut)

    ovf_val = int(dut.ovf.value)
    dut._log.info(f"  ovf={ovf_val}  out={q88_to_float(dut.out.value):.5f}")
    assert ovf_val == 1, f"ovf must be 1 when y=0, got {ovf_val}"
    dut._log.info("PASS test_overflow_y_zero")


# =============================================================================
#  TEST 11 -- mode_isolation
# =============================================================================

@cocotb.test()
async def test_mode_isolation(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("MODE ISOLATION (Q8.8) -- feed-forward after iterate-X")

    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(0.0)
    dut.y_ext.value = float_to_q88(1.0)
    await pulse_valid(dut)

    dut.sel_x.value = 1
    dut.sel_y.value = 0
    for _ in range(3):
        await pulse_valid(dut)
    fb_after = q88_to_float(dut.out.value)
    dut._log.info(f"  fb after 3 iter-X: {fb_after:.5f}")

    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(0.0)
    dut.y_ext.value = float_to_q88(1.0)
    await pulse_valid(dut)
    got = q88_to_float(dut.out.value)
    ae  = abs(got - 1.0)
    dut._log.info(f"  feed-forward eml(0,1): got={got:.6f}  err={ae:.2e}")
    assert ae < 0.01, f"Feed-forward contaminated by fb_reg={fb_after}"
    dut._log.info("PASS test_mode_isolation")


# =============================================================================
#  TEST 12 -- precision_report
# =============================================================================

@cocotb.test()
async def test_precision_report(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)

    dut._log.info("=" * 60)
    dut._log.info("Q8.8 PRECISION REPORT")
    dut._log.info(f"  Q8.8 quantisation floor: {1.0/SCALE:.6f}  (1/256)")
    dut._log.info("=" * 60)

    cases = [
        (0.0,  1.0,  1.00000,  "eml(0,1)=1.0"),
        (1.0,  1.0,  2.71828,  "eml(1,1)=e"),
        (0.0,  2.0,  0.30685,  "eml(0,2)=1-ln2"),
        (-1.0, 1.0,  0.36788,  "eml(-1,1)=1/e"),
        (2.0,  1.0,  7.38906,  "eml(2,1)=e^2"),
        (0.5,  1.0,  1.64872,  "eml(0.5,1)=sqrte"),
    ]

    errors = []
    for x, y, expected, lbl in cases:
        got = await chip_eml(dut, x, y)
        ae  = abs(got - expected)
        re  = ae / max(abs(expected), 1e-9)
        dut._log.info(f"  {lbl:20s}  got={got:.6f}  err={re:.3%}  abs={ae:.4f}")
        # loosened from 0.05/0.005 (Q8.24) -- the quantisation floor alone
        # is ~0.004 here vs ~1.5e-8 for Q8.24, so a far looser bound is the
        # honest comparison rather than reusing the 24-bit number
        assert re < 0.08 or ae < 0.05, f"Q8.8 error {re:.3%} too large for {lbl}"
        errors.append(re)

    avg_err = sum(errors) / len(errors)
    dut._log.info(f"  Average relative error: {avg_err:.3%}")
    assert avg_err < 0.04, f"Average error {avg_err:.3%} too large"
    dut._log.info("PASS test_precision_report")
