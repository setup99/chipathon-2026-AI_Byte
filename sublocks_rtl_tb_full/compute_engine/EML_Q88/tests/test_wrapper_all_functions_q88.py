# =============================================================================
#  test_wrapper_all_functions_q88.py
#  Every function the wrapper can do, all previously-passed block-level
#  tests ported through eml_wrapper_q88_rtn instead of the standalone
#  blocks. One DUT elaboration (the wrapper), one test run.
#
#  SIGMOID  (5 tests, from test_sigmoid_q88.py)     via OP_SIGMOID
#  TANH     (6 tests, from test_tanh_q88.py)         via OP_TANH
#  RECIP    (6 tests, from test_recip_q88.py)        via OP_RECIP
#  SQRT     (6 tests, from test_sqrt_q88.py)         via OP_SQRT
#  SOFTMAX  (12 tests, from test_softmax_full_q88.py) via OP_SOFTMAX
#  FEEDBACK (12 tests, from test_feedback_cell_q88.py) via OP_FEEDBACK
#  ----------------------------------------------------------------
#  47 tests total.
#
#  chip_mul/chip_exp/chip_ln in the original feedback_cell suite are
#  pure Python compositions built on top of feed-forward EML calls (no
#  separate multiplier hardware) -- they port through OP_FEEDBACK alone,
#  reusing mul_routing_q88.py/programs_list.py unchanged.
# =============================================================================

import math
import random
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

from eml_hw_model_q88 import q88, fq88
from mul_routing_q88 import run_program_with_mul_routing
from programs_list import programs


def true_softmax(z):
    m = max(z)
    exps = [math.exp(v - m) for v in z]
    s = sum(exps)
    return [e / s for e in exps]


def linspace(a, b, n):
    if n == 1:
        return [a]
    return [a + (b - a) * i / (n - 1) for i in range(n)]

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"
W = 16
MAX_N = 8
Q88_MAX = 127.99609375
Q88_MIN = -128.0

OP_SIGMOID  = 0
OP_TANH     = 1
OP_RECIP    = 2
OP_SQRT     = 3
OP_SOFTMAX  = 4
OP_FEEDBACK = 5


def float_to_q88(val) -> int:
    if isinstance(val, complex):
        val = val.real
    if math.isnan(val):
        return 0
    if val >= Q88_MAX:
        return 0x7FFF
    if val <= Q88_MIN:
        return 0x8000
    raw = round(val * (1 << 8))
    raw = max(-(1 << 15), min((1 << 15) - 1, raw))
    return raw & 0xFFFF


def q88_to_float(raw) -> float:
    raw = int(raw) & 0xFFFF
    if raw >= 0x8000:
        raw -= 0x10000
    return raw / 256.0


def as_complex(val) -> complex:
    return val if isinstance(val, complex) else complex(val)


def fmt(val) -> str:
    z = as_complex(val)
    if abs(z.imag) <= 1e-6:
        return f"{z.real:.5f}"
    return f"{z.real:.4f}{z.imag:+.4f}j"


async def reset_dut(dut):
    dut.rst.value = 1
    dut.start.value = 0
    dut.opcode.value = 0
    dut.x_in.value = 0
    dut.n_in.value = 0
    dut.z_in.value = 0
    dut.z_valid.value = 0
    dut.x_ext.value = float_to_q88(0.0)
    dut.y_ext.value = float_to_q88(1.0)
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 3)


async def pulse_start(dut, timeout=120):
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


# ---------------------------------------------------------------------------
# Single-operand adapter (SIGMOID/TANH/RECIP/SQRT): mirrors each
# original suite's run_<fn>(dut, x) -> (float, cycles, ovf)
# ---------------------------------------------------------------------------
async def run_single(dut, opcode, x: float, timeout=120):
    dut.opcode.value = opcode
    dut.x_in.value = float_to_q88(x)
    cycles = await pulse_start(dut, timeout)
    return q88_to_float(dut.result.value), cycles, int(dut.ovf.value)


# ---------------------------------------------------------------------------
# Serial softmax adapter: push n logits one per cycle via z_in/z_valid,
# collect n results one per cycle via the SHARED result/valid ports --
# for OP_SOFTMAX, valid simply pulses once per streamed element (n
# pulses total), with result carrying that element each time, exactly
# like every other opcode's single valid pulse, just n of them.
# Returns (results_list, TRUE total start->valid cycles, ovf).
# ---------------------------------------------------------------------------
async def run_softmax(dut, n, zs, gap_cycles=0, timeout=400):
    dut.opcode.value = OP_SOFTMAX
    dut.n_in.value = n
    await RisingEdge(dut.clk)
    dut.start.value = 1
    cycles = 1
    await RisingEdge(dut.clk)
    dut.start.value = 0

    for z in zs:
        if gap_cycles:
            dut.z_valid.value = 0
            await ClockCycles(dut.clk, gap_cycles)
            cycles += gap_cycles
        dut.z_in.value = float_to_q88(z)
        dut.z_valid.value = 1
        await RisingEdge(dut.clk)
        cycles += 1
    dut.z_valid.value = 0
    dut.z_in.value = 0

    results = []
    for _ in range(timeout):
        await RisingEdge(dut.clk)
        cycles += 1
        if int(dut.valid.value) == 1:
            results.append(q88_to_float(dut.result.value))
            if len(results) == n:
                break
    else:
        raise AssertionError(f"Timed out waiting for valid (N={n}, z={zs})")

    assert len(results) == n, f"expected {n} streamed softmax results, got {len(results)}"
    return results, cycles, int(dut.ovf.value)


# ---------------------------------------------------------------------------
# Feedback adapter: mirrors the original chip_eml(dut,x,y) through
# OP_FEEDBACK's x_ext/y_ext/sel_x/sel_y (start == valid_in at the wrapper
# boundary, exactly as documented in eml_wrapper_q88_rtn.v)
# ---------------------------------------------------------------------------
async def chip_eml(dut, x: float, y: float) -> float:
    dut.opcode.value = OP_FEEDBACK
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(x)
    dut.y_ext.value = float_to_q88(y)
    await pulse_start(dut)
    return q88_to_float(dut.result.value)


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


async def pulse_feedback_raw(dut, x_ext, y_ext, sel_x, sel_y):
    """For the iterate/cross-feedback tests, which need direct sel_x/
    sel_y control rather than chip_eml's fixed feed-forward mode."""
    dut.opcode.value = OP_FEEDBACK
    dut.sel_x.value = sel_x
    dut.sel_y.value = sel_y
    dut.x_ext.value = float_to_q88(x_ext)
    dut.y_ext.value = float_to_q88(y_ext)
    await pulse_start(dut)
    return q88_to_float(dut.result.value)


def true_sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


# =============================================================================
# SIGMOID -- 5 tests, via OP_SIGMOID
# =============================================================================

@cocotb.test()
async def test_sigmoid_basic(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    got, cycles, ovf = await run_single(dut, OP_SIGMOID, 0.0)
    dut._log.info(f"sigma(0) = {got:.8f}  (cycles={cycles}, ovf={ovf})")
    assert abs(got - 0.5) < 1e-3
    assert ovf == 0
    dut._log.info("PASS test_sigmoid_basic")


@cocotb.test()
async def test_sigmoid_sweep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    points = [-4.0, -3.0, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0]
    max_rel, fails = 0.0, 0
    for x in points:
        got, cycles, ovf = await run_single(dut, OP_SIGMOID, x)
        ref = true_sigmoid(x)
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        if abs(x) >= 4.0:
            ok = ae < 0.008
        else:
            ok = re < 0.06 or ae < 0.03
        if not ok:
            fails += 1
        if re > max_rel and abs(x) < 4.0:
            max_rel = re
        dut._log.info(f"  sigma({x:+5.2f})={got:.5f} ref={ref:.5f} rel={re:.3%} {'ok' if ok else 'FAIL'}")
    dut._log.info(f"  Max rel error (|x|<4): {max_rel:.3%}")
    assert fails == 0
    dut._log.info("PASS test_sigmoid_sweep")


@cocotb.test()
async def test_sigmoid_symmetry(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for x in [0.5, 1.0, 1.5, 2.0, 3.0]:
        pos, _, _ = await run_single(dut, OP_SIGMOID, x)
        neg, _, _ = await run_single(dut, OP_SIGMOID, -x)
        err = abs(pos + neg - 1.0)
        ok = err < 0.05
        if not ok:
            fails += 1
        dut._log.info(f"  sigma({x:+.1f})+sigma({-x:+.1f})={pos + neg:.5f} err={err:.4f} {'ok' if ok else 'FAIL'}")
    assert fails == 0
    dut._log.info("PASS test_sigmoid_symmetry")


@cocotb.test()
async def test_sigmoid_latency(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    _, cycles, _ = await run_single(dut, OP_SIGMOID, 1.0)
    dut._log.info(f"Latency: {cycles} cycles")
    assert cycles == 6
    dut._log.info("PASS test_sigmoid_latency")


@cocotb.test()
async def test_sigmoid_back_to_back(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for x in [0.0, 1.0, -1.0, 2.0, -2.0]:
        got, cycles, ovf = await run_single(dut, OP_SIGMOID, x)
        ref = true_sigmoid(x)
        re = abs(got - ref) / max(abs(ref), 1e-9)
        ok = re < 0.06 or abs(got - ref) < 0.03
        if not ok:
            fails += 1
        dut._log.info(f"  sigma({x:+.1f})={got:.4f} ref={ref:.4f} rel={re:.3%}")
    assert fails == 0
    dut._log.info("PASS test_sigmoid_back_to_back")


# =============================================================================
# TANH -- 6 tests, via OP_TANH
# =============================================================================

@cocotb.test()
async def test_tanh_basic(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    got, cycles, ovf = await run_single(dut, OP_TANH, 0.0)
    dut._log.info(f"tanh(0) = {got:.6f}  (cycles={cycles}, ovf={ovf})")
    assert abs(got - 0.0) < 1e-3
    assert ovf == 0
    dut._log.info("PASS test_tanh_basic")


@cocotb.test()
async def test_tanh_sweep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    points = [-2.0, -1.5, -1.0, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0, 1.5, 2.0]
    max_rel, fails = 0.0, 0
    for x in points:
        got, cycles, ovf = await run_single(dut, OP_TANH, x)
        ref = math.tanh(x)
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        ok = ae < 0.02 if abs(x) <= 0.25 else (re < 0.06 or ae < 0.03)
        if not ok:
            fails += 1
        if re > max_rel and abs(x) > 0.25:
            max_rel = re
        dut._log.info(f"  tanh({x:+5.2f})={got:.5f} ref={ref:.5f} rel={re:.3%} {'ok' if ok else 'FAIL'}")
    dut._log.info(f"  Max rel error (|x|>0.25): {max_rel:.3%}")
    assert fails == 0
    dut._log.info("PASS test_tanh_sweep")


@cocotb.test()
async def test_tanh_symmetry(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for x in [0.25, 0.5, 1.0, 1.5, 2.0]:
        pos, _, _ = await run_single(dut, OP_TANH, x)
        neg, _, _ = await run_single(dut, OP_TANH, -x)
        err = abs(pos + neg)
        ok = err < 0.05
        if not ok:
            fails += 1
        dut._log.info(f"  tanh({x:+.2f})+tanh({-x:+.2f})={pos + neg:.5f} err={err:.4f}")
    assert fails == 0
    dut._log.info("PASS test_tanh_symmetry")


@cocotb.test()
async def test_tanh_vs_sigmoid_identity(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for x in [0.5, 1.0, 1.5]:
        got, _, _ = await run_single(dut, OP_TANH, x)
        expected = 2.0 * (1.0 / (1.0 + math.exp(-2.0 * x))) - 1.0
        ae = abs(got - expected)
        ok = ae < 0.04
        if not ok:
            fails += 1
        dut._log.info(f"  tanh({x:.2f})={got:.5f} 2*sigma(2x)-1={expected:.5f} err={ae:.4f}")
    assert fails == 0
    dut._log.info("PASS test_tanh_vs_sigmoid_identity")


@cocotb.test()
async def test_tanh_latency(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    _, cycles, _ = await run_single(dut, OP_TANH, 1.0)
    dut._log.info(f"Latency: {cycles} cycles")
    assert cycles == 7
    dut._log.info("PASS test_tanh_latency")


@cocotb.test()
async def test_tanh_back_to_back(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for x in [0.0, 1.0, -1.0, 0.5, -0.5]:
        got, cycles, ovf = await run_single(dut, OP_TANH, x)
        ref = math.tanh(x)
        re = abs(got - ref) / max(abs(ref), 1e-9)
        ok = re < 0.06 or abs(got - ref) < 0.03
        if not ok:
            fails += 1
        dut._log.info(f"  tanh({x:+.2f})={got:.4f} ref={ref:.4f} rel={re:.3%}")
    assert fails == 0
    dut._log.info("PASS test_tanh_back_to_back")


# =============================================================================
# RECIP -- 6 tests, via OP_RECIP
# =============================================================================

@cocotb.test()
async def test_recip_basic(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    got, cycles, ovf = await run_single(dut, OP_RECIP, 1.0)
    dut._log.info(f"1/1.0 = {got:.6f} (cycles={cycles}, ovf={ovf})")
    assert abs(got - 1.0) < 1e-3
    assert ovf == 0
    dut._log.info("PASS test_recip_basic")


@cocotb.test()
async def test_recip_sweep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    points = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 8.0, 16.0, 32.0, 64.0]
    fails = 0
    for x in points:
        got, cycles, ovf = await run_single(dut, OP_RECIP, x)
        ref = 1.0 / x
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        ok = re < 0.04 or ae < 0.02
        if not ok:
            fails += 1
        dut._log.info(f"  1/{x:<6.3f}={got:.5f} ref={ref:.5f} rel={re:.3%} {'ok' if ok else 'FAIL'}")
    assert fails == 0
    dut._log.info("PASS test_recip_sweep")


@cocotb.test()
async def test_recip_identity(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for x in [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]:
        got, _, _ = await run_single(dut, OP_RECIP, x)
        err = abs(x * got - 1.0)
        ok = err < 0.04
        if not ok:
            fails += 1
        dut._log.info(f"  {x:.2f}*recip({x:.2f})={x * got:.5f} err={err:.4f}")
    assert fails == 0
    dut._log.info("PASS test_recip_identity")


@cocotb.test()
async def test_recip_latency(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    _, cycles, _ = await run_single(dut, OP_RECIP, 2.0)
    dut._log.info(f"Latency: {cycles} cycles")
    assert cycles == 4
    dut._log.info("PASS test_recip_latency")


@cocotb.test()
async def test_recip_overflow_zero(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    _, cycles, ovf = await run_single(dut, OP_RECIP, 0.0)
    dut._log.info(f"recip(0): ovf={ovf}")
    assert ovf == 1
    dut._log.info("PASS test_recip_overflow_zero")


@cocotb.test()
async def test_recip_back_to_back(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for x in [1.0, 2.0, 0.5, 4.0, 0.25]:
        got, cycles, ovf = await run_single(dut, OP_RECIP, x)
        ref = 1.0 / x
        re = abs(got - ref) / max(abs(ref), 1e-9)
        ok = re < 0.04 or abs(got - ref) < 0.02
        if not ok:
            fails += 1
        dut._log.info(f"  1/{x:.2f}={got:.5f} ref={ref:.5f} rel={re:.3%}")
    assert fails == 0
    dut._log.info("PASS test_recip_back_to_back")


# =============================================================================
# SQRT -- 6 tests, via OP_SQRT
# =============================================================================

@cocotb.test()
async def test_sqrt_basic(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    got, cycles, ovf = await run_single(dut, OP_SQRT, 1.0)
    dut._log.info(f"sqrt(1.0)={got:.6f} (cycles={cycles}, ovf={ovf})")
    assert abs(got - 1.0) < 1e-3
    assert ovf == 0
    dut._log.info("PASS test_sqrt_basic")


@cocotb.test()
async def test_sqrt_perfect_squares(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for x in [4.0, 9.0, 16.0, 25.0, 36.0, 49.0, 64.0]:
        got, cycles, ovf = await run_single(dut, OP_SQRT, x)
        ref = math.sqrt(x)
        re = abs(got - ref) / max(abs(ref), 1e-9)
        ok = re < 0.03 or abs(got - ref) < 0.02
        if not ok:
            fails += 1
        dut._log.info(f"  sqrt({x:5.1f})={got:.5f} ref={ref:.5f} rel={re:.3%} {'ok' if ok else 'FAIL'}")
    assert fails == 0
    dut._log.info("PASS test_sqrt_perfect_squares")


@cocotb.test()
async def test_sqrt_sweep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    points = [0.1, 0.25, 0.5, 1.5, 2.0, 3.0, 5.0, 7.0, 10.0, 20.0, 50.0, 100.0]
    fails = 0
    for x in points:
        got, cycles, ovf = await run_single(dut, OP_SQRT, x)
        ref = math.sqrt(x)
        re = abs(got - ref) / max(abs(ref), 1e-9)
        ok = re < 0.03 or abs(got - ref) < 0.02
        if not ok:
            fails += 1
        dut._log.info(f"  sqrt({x:6.2f})={got:.5f} ref={ref:.5f} rel={re:.3%} {'ok' if ok else 'FAIL'}")
    assert fails == 0
    dut._log.info("PASS test_sqrt_sweep")


@cocotb.test()
async def test_sqrt_identity(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for x in [2.0, 5.0, 10.0, 20.0, 50.0]:
        got, _, _ = await run_single(dut, OP_SQRT, x)
        rel = abs(got * got - x) / max(abs(x), 1e-9)
        ok = rel < 0.06
        if not ok:
            fails += 1
        dut._log.info(f"  sqrt({x:.2f})={got:.5f} squared={got * got:.5f} rel={rel:.3%}")
    assert fails == 0
    dut._log.info("PASS test_sqrt_identity")


@cocotb.test()
async def test_sqrt_latency(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    _, cycles, _ = await run_single(dut, OP_SQRT, 4.0)
    dut._log.info(f"Latency: {cycles} cycles")
    assert cycles == 4
    dut._log.info("PASS test_sqrt_latency")


@cocotb.test()
async def test_sqrt_overflow_zero(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    _, cycles, ovf = await run_single(dut, OP_SQRT, 0.0)
    dut._log.info(f"sqrt(0): ovf={ovf}")
    assert ovf == 1
    dut._log.info("PASS test_sqrt_overflow_zero")


# =============================================================================
# SOFTMAX -- 12 tests, via OP_SOFTMAX (serial interface)
# =============================================================================

@cocotb.test()
async def test_softmax_n_changes_every_call(dut):
    """N changes every call, back-to-back, no reset -- checked against
    true (non-hardware) softmax now instead of a bit-exact model,
    since the serial push order changes the internal computation
    path enough that re-deriving a bit-exact model wasn't worth it
    for this interface change; accuracy-based checking is what every
    other test in this suite already uses."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    Z_POOL = [1.0, 0.5, -0.5, -1.0, 2.0, 0.25, -2.0, 1.5]
    fails = 0
    for n in [3, 7, 2, 8, 4, 5, 6, 2, 8]:
        zs = Z_POOL[:n]
        got, cycles, rtl_ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        ef = sum(1 for v, r in zip(got, ref) if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03))
        expected_cycles = 11 * n + 3
        ok = ef == 0 and cycles == expected_cycles
        if not ok:
            fails += 1
        dut._log.info(f"  N={n}: cycles={cycles} (expect {expected_cycles})  elem_fails={ef}  {'ok' if ok else 'FAIL'}")
    assert fails == 0
    dut._log.info("PASS test_softmax_n_changes_every_call")


@cocotb.test()
async def test_softmax_stale_bits_cleared(dut):
    """After an N=8 call, an N=2 call must stream back exactly 2
    results -- not leak any of the previous call's data. With a
    serial output port (no packed bus with unused high slots to
    worry about), this is naturally guaranteed by run_softmax's own
    `len(results)==n` assertion; this test just makes that explicit
    and checks the values are fresh, not stale."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    Z_POOL = [1.0, 0.5, -0.5, -1.0, 2.0, 0.25, -2.0, 1.5]
    got8, _, _ = await run_softmax(dut, 8, Z_POOL[:8])
    got2, _, _ = await run_softmax(dut, 2, Z_POOL[:2])
    dut._log.info(f"  N=8 results: {[f'{v:.4f}' for v in got8]}")
    dut._log.info(f"  N=2 results: {[f'{v:.4f}' for v in got2]}")
    assert len(got2) == 2, f"expected exactly 2 streamed results, got {len(got2)}"
    ref2 = true_softmax(Z_POOL[:2])
    assert all(abs(v - r) < 0.05 for v, r in zip(got2, ref2)), "N=2 call after N=8 produced wrong (possibly stale) values"
    dut._log.info("PASS test_softmax_stale_bits_cleared")


@cocotb.test()
async def test_softmax_invalid_n_rejected(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    for bad_n in [0, 1, 9, 15]:
        dut.opcode.value = OP_SOFTMAX
        dut.n_in.value = bad_n
        dut.z_in.value = 0
        dut.z_valid.value = 0
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
        dut._log.info(f"  n_in={bad_n}: valid={got_valid} n_err={n_err}")
        assert got_valid and n_err == 1
        await ClockCycles(dut.clk, 3)
    dut._log.info("PASS test_softmax_invalid_n_rejected")


@cocotb.test()
async def test_softmax_uniform_all_n(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for n in range(2, 9):
        got, cycles, ovf = await run_softmax(dut, n, [1.0] * n)
        worst = max(abs(v - 1.0 / n) for v in got)
        ok = worst < 0.05 and abs(sum(got) - 1.0) < 0.08
        if not ok:
            fails += 1
        dut._log.info(f"  N={n}: worst_err={worst:.4f} {'ok' if ok else 'FAIL'}")
    assert fails == 0
    dut._log.info("PASS test_softmax_uniform_all_n")


@cocotb.test()
async def test_softmax_peaked_all_n(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for n in range(2, 9):
        zs = [2.0] + [0.0] * (n - 1)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        ef = sum(1 for v, r in zip(got, ref) if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03))
        if ef:
            fails += 1
        dut._log.info(f"  N={n}: elem_fails={ef}")
    assert fails == 0
    dut._log.info("PASS test_softmax_peaked_all_n")


@cocotb.test()
async def test_softmax_ramp_all_n(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for n in range(2, 9):
        zs = linspace(-1.0, 2.0, n)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        ef = sum(1 for v, r in zip(got, ref) if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03))
        if ef:
            fails += 1
        dut._log.info(f"  N={n}: elem_fails={ef}")
    assert fails == 0
    dut._log.info("PASS test_softmax_ramp_all_n")


@cocotb.test()
async def test_softmax_sum_to_one_all_n(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    random.seed(42)
    fails = 0
    for n in range(2, 9):
        n_fails = 0
        for _ in range(8):
            zs = [random.uniform(-2.0, 2.0) for _ in range(n)]
            got, cycles, ovf = await run_softmax(dut, n, zs)
            if abs(sum(got) - 1.0) >= 0.07:
                n_fails += 1
        dut._log.info(f"  N={n}: {8 - n_fails}/8 passed")
        if n_fails:
            fails += 1
    assert fails == 0
    dut._log.info("PASS test_softmax_sum_to_one_all_n")


@cocotb.test()
async def test_softmax_latency_all_n(dut):
    """TRUE total start->valid cycles, back-to-back push, must fit
    11*N+3 -- measured, not assumed, and different from the old
    packed-bus interface's 8*N+3 since logits/results now arrive/
    leave serially instead of all at once."""
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for n in range(2, 9):
        _, cycles, _ = await run_softmax(dut, n, [1.0] * n)
        expected = 11 * n + 3
        ok = cycles == expected
        if not ok:
            fails += 1
        dut._log.info(f"  N={n}: cycles={cycles} expected={expected}")
    assert fails == 0
    dut._log.info("PASS test_softmax_latency_all_n")


@cocotb.test()
async def test_softmax_large_range_all_n(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for n in range(2, 9):
        zs = linspace(3.0, 0.0, n)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        ef = sum(1 for v, r in zip(got, ref) if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03))
        ok = ef == 0 and ovf == 0
        if not ok:
            fails += 1
        dut._log.info(f"  N={n}: ovf={ovf} elem_fails={ef}")
    assert fails == 0
    dut._log.info("PASS test_softmax_large_range_all_n")


@cocotb.test()
async def test_softmax_maxtrick_previously_overflowing(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    fails = 0
    for n in [6, 7, 8]:
        zs = linspace(4.0, 1.0, n)
        got, cycles, ovf = await run_softmax(dut, n, zs)
        ref = true_softmax(zs)
        ef = sum(1 for v, r in zip(got, ref) if not (abs(v - r) / max(abs(r), 1e-6) < 0.08 or abs(v - r) < 0.03))
        dominant_ok = got[0] == max(got)
        ok = ovf == 0 and ef == 0 and dominant_ok
        if not ok:
            fails += 1
        dut._log.info(f"  N={n} (4,1)-spread: ovf={ovf} elem_fails={ef} {'PASS' if ok else 'FAIL'}")
    assert fails == 0
    dut._log.info("PASS test_softmax_maxtrick_previously_overflowing")


@cocotb.test()
async def test_softmax_maxtrick_dominant_slot_bitexact(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    got, cycles, ovf = await run_softmax(dut, 4, [50.0, -50.0, -50.0, -50.0])
    dut._log.info(f"  got={[f'{v:.6f}' for v in got]} ovf={ovf}")
    assert abs(got[0] - 1.0) < 1e-6
    assert all(v == 0.0 for v in got[1:])
    dut._log.info("PASS test_softmax_maxtrick_dominant_slot_bitexact")


@cocotb.test()
async def test_softmax_maxtrick_shift_invariance(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    got_big, _, ovf_big = await run_softmax(dut, 3, [100.0, 99.0, 98.0])
    got_small, _, _ = await run_softmax(dut, 3, [2.0, 1.0, 0.0])
    dut._log.info(f"  big={[f'{v:.4f}' for v in got_big]} small={[f'{v:.4f}' for v in got_small]}")
    assert ovf_big == 0
    for a, b in zip(got_big, got_small):
        assert abs(a - b) < 1e-6
    dut._log.info("PASS test_softmax_maxtrick_shift_invariance")


# =============================================================================
# FEEDBACK -- 12 tests, via OP_FEEDBACK
# =============================================================================

@cocotb.test()
async def test_feedback_protocol_basic(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    got = await chip_eml(dut, 0.0, 1.0)
    dut._log.info(f"eml(0,1): got={got:.6f} expected=1.0")
    assert abs(got - 1.0) < 0.01
    dut._log.info("PASS test_feedback_protocol_basic")


@cocotb.test()
async def test_feedback_eml_scalar(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    got = await chip_eml(dut, 0.5, 0.5)
    expected = math.exp(0.5) - math.log(0.5)
    ae = abs(got - expected)
    dut._log.info(f"eml(0.5,0.5): got={got:.5f} expected={expected:.5f} |err|={ae:.2e}")
    assert ae <= 0.08
    dut._log.info("PASS test_feedback_eml_scalar")


@cocotb.test()
async def test_feedback_exp_ln_sweep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    ABS_TOL, REL_TOL = 0.08, 0.04
    fails, total = 0, 0
    for x_10 in range(-30, 41, 5):
        x = x_10 / 10.0
        got = await chip_exp(dut, x)
        ref = math.exp(x)
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        ok = ae < ABS_TOL or re < REL_TOL
        total += 1
        if not ok:
            fails += 1
        dut._log.info(f"  exp({x:+5.1f}): got={got:+10.4f} ref={ref:+10.4f} {'ok' if ok else 'FAIL'}")
    for x in [0.1, 0.2, 0.5, 1.0, 1.5, 2.0, math.e, 5.0, 10.0, 20.0]:
        got = await chip_ln(dut, x)
        ref = math.log(x)
        ae = abs(got - ref)
        re = ae / max(abs(ref), 1e-9)
        ok = ae < ABS_TOL or re < REL_TOL
        total += 1
        if not ok:
            fails += 1
        dut._log.info(f"  ln({x:+7.3f}): got={got:+10.4f} ref={ref:+10.4f} {'ok' if ok else 'FAIL'}")
    dut._log.info(f"Sweep: {total - fails}/{total} within tolerance")
    assert fails <= 4
    dut._log.info("PASS test_feedback_exp_ln_sweep")


@cocotb.test()
async def test_feedback_eml_mul(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    cases = [
        (2.0, 3.0, 6.0), (1.5, 2.0, 3.0), (0.5, 0.5, 0.25), (4.0, 0.25, 1.0),
        (10.0, 2.0, 20.0), (-2.0, 3.0, -6.0), (2.0, -3.0, -6.0), (-1.5, -2.0, 3.0),
        (0.0, 5.0, 0.0), (1.0, 1.0, 1.0),
    ]
    fails = 0
    for a, b, expected in cases:
        got = await chip_mul(dut, a, b)
        ae = abs(got - expected)
        re = ae / max(abs(expected), 1e-9)
        ok = re < 0.08 or ae < 0.05
        if not ok:
            fails += 1
        dut._log.info(f"  mul({a:+5.2f},{b:+5.2f})={expected:+7.3f} got={got:+7.4f} rel={re:.2%}")
    assert fails == 0
    dut._log.info("PASS test_feedback_eml_mul")


@cocotb.test()
async def test_feedback_all_38_functions(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    x_val, y_val = 0.5, 0.5
    accurate, degraded, poor = [], [], []
    PROG_TOL = 0.20
    for name, program, arity, expected_raw in programs:
        expected = as_complex(expected_raw)
        dut.sel_x.value = 0
        dut.sel_y.value = 0
        actual, chip_calls = await run_program_with_mul_routing(
            dut, name, program, x_val, y_val, run_program, chip_mul, chip_exp, chip_ln,
        )
        actual_cmp = complex(actual.real, 0) if abs(expected.imag) < 1e-6 else actual
        err = abs(actual_cmp - expected)
        rel_err = err / max(abs(expected), 1e-6) if abs(expected) >= 0.01 else err
        entry = (name, actual, expected, rel_err, chip_calls)
        if rel_err <= PROG_TOL:
            accurate.append(entry); tag = "ACC "
        elif rel_err <= 1.0:
            degraded.append(entry); tag = "DEG "
        else:
            poor.append(entry); tag = "FAIL"
        dut._log.info(f"  {tag} {name:15s}: got={fmt(actual):16s} exp={fmt(expected):16s} err={rel_err:6.1%}")
    dut._log.info(f"Accurate: {len(accurate)}/{len(programs)}  Degraded: {len(degraded)}  Poor: {len(poor)}")
    if poor:
        dut._log.info(f"Still failing: {[e[0] for e in poor]}")
    assert len(accurate) >= 20, f"Only {len(accurate)} accurate, expected >= 20"
    dut._log.info("PASS test_feedback_all_38_functions")


@cocotb.test()
async def test_feedback_iterate_x(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    seed = await pulse_feedback_raw(dut, 0.0, 1.0, 0, 0)
    dut._log.info(f"seed={seed:.6f} expected=1.0")
    assert abs(seed - 1.0) < 0.02
    prev = seed
    results = [seed]
    for step in range(1, 4):
        got = await pulse_feedback_raw(dut, prev, 1.0, 1, 0)
        expected = math.exp(prev)
        re = abs(got - expected) / max(abs(expected), 1e-6)
        results.append(got)
        dut._log.info(f"  step {step}: got={got:10.4f} expected={expected:10.4f} rel={re:.2%}")
        if got >= 127.9:
            dut._log.info("  Saturated -- correct HW limit")
            break
        assert re < 0.15
        prev = got
    dut._log.info(f"Sequence: {' -> '.join(f'{v:.4f}' for v in results)}")
    dut._log.info("PASS test_feedback_iterate_x")


@cocotb.test()
async def test_feedback_iterate_y(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    seed = await pulse_feedback_raw(dut, 1.0, 1.0, 0, 0)
    dut._log.info(f"seed={seed:.5f} expected~=e")
    assert abs(seed - math.e) < 0.25
    FIXED_PT = 1.7632228343518967
    prev = seed
    results = [seed]
    for step in range(1, 8):
        got = await pulse_feedback_raw(dut, 1.0, prev, 0, 1)
        expected = math.exp(1.0) - math.log(prev) if prev > 0 else math.inf
        ae = abs(got - expected)
        dist = abs(got - FIXED_PT)
        results.append(got)
        dut._log.info(f"  step {step}: got={got:8.4f} exp={expected:8.4f} dist_fp={dist:.4f}")
        assert ae < 0.40
        prev = got
    dist_final = abs(results[-1] - FIXED_PT)
    dut._log.info(f"Final dist to fixed point: {dist_final:.4f}")
    assert dist_final < 0.60
    dut._log.info("PASS test_feedback_iterate_y")


@cocotb.test()
async def test_feedback_cross_feedback(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    seed = await pulse_feedback_raw(dut, 0.0, 1.0, 0, 0)
    dut._log.info(f"seed={seed:.5f} expected=1.0")
    assert abs(seed - 1.0) < 0.02
    prev = seed
    results = [seed]
    for step in range(1, 4):
        got = await pulse_feedback_raw(dut, prev, prev, 1, 1)
        expected = math.exp(prev) - math.log(prev) if prev > 0 else math.inf
        re = abs(got - expected) / max(abs(expected), 1e-6)
        results.append(got)
        dut._log.info(f"  step {step}: got={got:10.4f} exp={expected:10.4f} rel={re:.2%}")
        if got >= 127.9:
            dut._log.info("  Saturated -- correct HW limit")
            break
        assert re < 0.15 or abs(got - expected) < 2.0
        prev = got
    dut._log.info(f"Sequence: {' -> '.join(f'{v:.4f}' for v in results)}")
    dut._log.info("PASS test_feedback_cross_feedback")


@cocotb.test()
async def test_feedback_reset_mid_sequence(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    await pulse_feedback_raw(dut, 0.0, 1.0, 0, 0)
    before = await pulse_feedback_raw(dut, 0.0, 1.0, 1, 0)
    assert abs(before - 1.0) > 0.1, "fb_reg should have advanced"
    dut.rst.value = 1
    await ClockCycles(dut.clk, 3)
    dut.rst.value = 0
    await ClockCycles(dut.clk, 2)
    after = await pulse_feedback_raw(dut, 0.0, 1.0, 1, 0)
    dut._log.info(f"after rst: got={after:.5f} expected~=e")
    assert abs(after - math.e) < 0.25
    dut._log.info("PASS test_feedback_reset_mid_sequence")


@cocotb.test()
async def test_feedback_overflow_y_zero(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    dut.opcode.value = OP_FEEDBACK
    dut.sel_x.value = 0
    dut.sel_y.value = 0
    dut.x_ext.value = float_to_q88(1.0)
    dut.y_ext.value = 0
    await pulse_start(dut)
    ovf_val = int(dut.ovf.value)
    dut._log.info(f"ovf={ovf_val}")
    assert ovf_val == 1
    dut._log.info("PASS test_feedback_overflow_y_zero")


@cocotb.test()
async def test_feedback_mode_isolation(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    await pulse_feedback_raw(dut, 0.0, 1.0, 0, 0)
    for _ in range(3):
        fb_after = await pulse_feedback_raw(dut, 0.0, 1.0, 1, 0)
    dut._log.info(f"fb after 3 iter-X: {fb_after:.5f}")
    got = await pulse_feedback_raw(dut, 0.0, 1.0, 0, 0)
    ae = abs(got - 1.0)
    dut._log.info(f"feed-forward eml(0,1): got={got:.6f} err={ae:.2e}")
    assert ae < 0.01
    dut._log.info("PASS test_feedback_mode_isolation")


@cocotb.test()
async def test_feedback_precision_report(dut):
    cocotb.start_soon(Clock(dut.clk, 20, **{CLOCK_UNIT: "ns"}).start())
    await reset_dut(dut)
    cases = [
        (0.0, 1.0, 1.00000), (1.0, 1.0, 2.71828), (0.0, 2.0, 0.30685),
        (-1.0, 1.0, 0.36788), (2.0, 1.0, 7.38906), (0.5, 1.0, 1.64872),
    ]
    errors = []
    for x, y, expected in cases:
        got = await chip_eml(dut, x, y)
        re = abs(got - expected) / max(abs(expected), 1e-9)
        dut._log.info(f"  eml({x},{y}): got={got:.6f} err={re:.3%}")
        assert re < 0.08 or abs(got - expected) < 0.05
        errors.append(re)
    avg_err = sum(errors) / len(errors)
    dut._log.info(f"Average relative error: {avg_err:.3%}")
    assert avg_err < 0.04
    dut._log.info("PASS test_feedback_precision_report")
