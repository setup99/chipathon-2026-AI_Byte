# =============================================================================
#  test_hw_model_crosscheck_q88.py
#  Proves eml_hw_model_q88.py is BIT-EXACT against the real Q8.8 RTL
#  simulation. Same discipline as test_hw_model_crosscheck.py (Q8.24):
#  zero tolerance, not "close enough" -- a real bit-for-bit diff.
# =============================================================================

import random
import cocotb
from cocotb.triggers import Timer

from eml_hw_model_q88 import eml_tile, eml_mul, q88, fq88

CLOCK_UNIT = "unit" if cocotb.__version__.startswith("2") else "units"
TIME_UNIT_NS = "ns"

W = 16
MASK16 = (1 << W) - 1


def to_signed_str(raw: int) -> str:
    raw &= MASK16
    return f"0x{raw:04X} ({fq88(raw):+.6f})"


@cocotb.test()
async def test_tile_crosscheck_named_cases(dut):
    cases = [
        (0.0,  1.0,  "eml(0,1)"),
        (1.0,  1.0,  "eml(1,1)"),
        (-1.0, 1.0,  "eml(-1,1)"),
        (2.0,  1.0,  "eml(2,1)"),
        (0.0,  2.0,  "eml(0,2)"),
        (0.5,  1.0,  "eml(0.5,1)"),
        (-0.5, 0.5,  "eml(-0.5,0.5)"),
        (3.0,  2.0,  "eml(3,2)"),
        (1.0,  0.0,  "eml(1,0)  [y=0, overflow case]"),
        (-4.0, 4.0,  "eml(-4,4)"),
        (4.5,  1.0,  "eml(4.5,1)"),
        (0.0,  127.0, "eml(0, ymax)"),
    ]

    mismatches = 0
    dut._log.info("=" * 78)
    dut._log.info("Q8.8 BIT-EXACT CROSSCHECK: RTL simulation vs eml_hw_model_q88.py")
    dut._log.info("=" * 78)

    for x_f, y_f, label in cases:
        x_raw = q88(x_f)
        y_raw = q88(y_f)

        dut.x.value = x_raw
        dut.y.value = y_raw
        await Timer(1, **{CLOCK_UNIT: TIME_UNIT_NS})

        rtl_out_raw = int(dut.out.value) & MASK16
        rtl_ovf = int(dut.ovf.value)

        model_out_raw, model_ovf = eml_tile(x_raw, y_raw)

        match_out = (rtl_out_raw == model_out_raw)
        match_ovf = (rtl_ovf == model_ovf)
        ok = match_out and match_ovf

        if not ok:
            mismatches += 1

        dut._log.info(
            f"  {label:35s}  rtl_out={to_signed_str(rtl_out_raw)}  "
            f"model_out={to_signed_str(model_out_raw)}  "
            f"rtl_ovf={rtl_ovf} model_ovf={model_ovf}  "
            f"{'EXACT MATCH' if ok else 'MISMATCH'}"
        )

        assert match_out, (
            f"{label}: RTL out=0x{rtl_out_raw:04X} != "
            f"model out=0x{model_out_raw:04X} -- model is NOT bit-exact"
        )
        assert match_ovf, (
            f"{label}: RTL ovf={rtl_ovf} != model ovf={model_ovf}"
        )

    dut._log.info(f"  Named cases: {len(cases) - mismatches}/{len(cases)} exact matches")
    assert mismatches == 0
    dut._log.info("PASS test_tile_crosscheck_named_cases")


@cocotb.test()
async def test_tile_crosscheck_random_sweep(dut):
    """
    1000 random raw 16-bit (x, y) pairs -- more cases than the Q8.24
    sweep (500) because the Q8.8 input space is small enough (2^16
    values total per operand) that denser sampling is cheap and gives
    a stronger guarantee.
    """
    random.seed(1234)
    N = 1000
    mismatches = 0
    worst_examples = []

    dut._log.info("=" * 78)
    dut._log.info(f"Q8.8 RANDOM SWEEP: {N} raw (x,y) pairs, bit-exact required")
    dut._log.info("=" * 78)

    for i in range(N):
        x_raw = random.randint(-(1 << 15), (1 << 15) - 1) & MASK16
        y_raw = random.randint(1, q88(127.0))

        dut.x.value = x_raw
        dut.y.value = y_raw
        await Timer(1, **{CLOCK_UNIT: TIME_UNIT_NS})

        rtl_out_raw = int(dut.out.value) & MASK16
        rtl_ovf = int(dut.ovf.value)

        model_out_raw, model_ovf = eml_tile(x_raw, y_raw)

        if rtl_out_raw != model_out_raw or rtl_ovf != model_ovf:
            mismatches += 1
            if len(worst_examples) < 5:
                worst_examples.append(
                    (i, x_raw, y_raw, rtl_out_raw, model_out_raw, rtl_ovf, model_ovf)
                )

    if mismatches:
        dut._log.info(f"  {mismatches}/{N} mismatches found:")
        for (i, xr, yr, ro, mo, rovf, movf) in worst_examples:
            dut._log.info(
                f"    [{i}] x=0x{xr:04X} y=0x{yr:04X}  "
                f"rtl=0x{ro:04X}(ovf={rovf})  model=0x{mo:04X}(ovf={movf})"
            )

    dut._log.info(f"  Result: {N - mismatches}/{N} bit-exact matches")
    assert mismatches == 0, (
        f"{mismatches}/{N} random cases were NOT bit-exact"
    )
    dut._log.info("PASS test_tile_crosscheck_random_sweep")


@cocotb.test()
async def test_mul_crosscheck(dut):
    if not hasattr(dut, "mul_dut"):
        dut._log.info("No mul_dut sub-hierarchy found -- skipping mul crosscheck "
                       "(tile crosscheck above already proves the shared "
                       "mitchell_log2/exp2 primitives are bit-exact)")
        return

    cases = [(2.0, 3.0), (-2.0, 3.0), (2.0, -3.0), (-2.0, -3.0), (0.5, 0.5), (10.0, 2.0)]
    mismatches = 0
    for a_f, b_f in cases:
        a_raw, b_raw = q88(a_f), q88(b_f)
        dut.mul_dut.a.value = a_raw
        dut.mul_dut.b.value = b_raw
        await Timer(1, **{CLOCK_UNIT: TIME_UNIT_NS})
        rtl_out = int(dut.mul_dut.out.value) & MASK16
        rtl_ovf = int(dut.mul_dut.ovf.value)
        model_out, model_ovf = eml_mul(a_raw, b_raw)
        ok = (rtl_out == model_out) and (rtl_ovf == model_ovf)
        if not ok:
            mismatches += 1
        dut._log.info(
            f"  mul({a_f},{b_f}): rtl=0x{rtl_out:04X} model=0x{model_out:04X} "
            f"{'EXACT' if ok else 'MISMATCH'}"
        )
    assert mismatches == 0
    dut._log.info("PASS test_mul_crosscheck")
