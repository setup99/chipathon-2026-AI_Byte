# =============================================================================
#  mul_routing_q88.py
#  Adapted from mul_routing.py (Q8.24) for the Q8.8 lightweight DUT.
#  Same routing decision, same 8 multiply-shaped functions, no change in
#  reasoning -- only the chip_* helper signatures differ because the Q8.8
#  testbench passes raw 16-bit encode/decode instead of 32-bit.
# =============================================================================

import math

MULTIPLY_SHAPED = {
    "HALF":     1,
    "SQR":      1,
    "SQRT":     1,
    "MUL":      2,
    "DIV":      2,
    "LOG_BASE": 2,
    "AVG":      2,
    "HYPOT":    2,
}


async def route_multiply_shaped(dut, name, x_val, y_val, chip_mul, chip_exp, chip_ln):
    x, y = x_val, y_val

    if name == "HALF":
        r = await chip_mul(dut, x, 0.5)
        return complex(r, 0.0)

    if name == "SQR":
        r = await chip_mul(dut, x, x)
        return complex(r, 0.0)

    if name == "SQRT":
        if x <= 0.0:
            return complex(0.0, 0.0)
        ln_x = await chip_ln(dut, x)
        r = await chip_exp(dut, ln_x / 2.0)
        return complex(r, 0.0)

    if name == "MUL":
        r = await chip_mul(dut, x, y)
        return complex(r, 0.0)

    if name == "DIV":
        if y == 0.0:
            return complex(math.inf, 0.0)
        ln_y = await chip_ln(dut, y)
        inv_y = await chip_exp(dut, -ln_y)
        r = await chip_mul(dut, x, inv_y)
        return complex(r, 0.0)

    if name == "LOG_BASE":
        if x <= 0.0 or y <= 0.0 or y == 1.0:
            return complex(math.nan, 0.0)
        ln_x = await chip_ln(dut, x)
        ln_y = await chip_ln(dut, y)
        return complex(ln_x / ln_y, 0.0)

    if name == "AVG":
        half_x = await chip_mul(dut, x, 0.5)
        half_y = await chip_mul(dut, y, 0.5)
        return complex(half_x + half_y, 0.0)

    if name == "HYPOT":
        x2 = await chip_mul(dut, x, x)
        y2 = await chip_mul(dut, y, y)
        s = x2 + y2
        if s <= 0.0:
            return complex(0.0, 0.0)
        ln_s = await chip_ln(dut, s)
        r = await chip_exp(dut, ln_s / 2.0)
        return complex(r, 0.0)

    raise KeyError(f"{name} is not in MULTIPLY_SHAPED")


async def run_program_with_mul_routing(
    dut, name, program, x_val, y_val, run_program_fallback, chip_mul, chip_exp, chip_ln
):
    if name in MULTIPLY_SHAPED:
        result = await route_multiply_shaped(
            dut, name, x_val, y_val, chip_mul, chip_exp, chip_ln
        )
        call_counts = {
            "HALF": 1, "SQR": 1, "SQRT": 2, "MUL": 1,
            "DIV": 3, "LOG_BASE": 2, "AVG": 2, "HYPOT": 5,
        }
        return result, call_counts[name]

    return await run_program_fallback(dut, program, x_val, y_val)
