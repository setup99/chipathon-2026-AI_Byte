# =============================================================================
#  eml_hw_model_q88.py
#  Bit-exact Python model of the Q8.8 lightweight EML hardware stack.
#
#  Same discipline as eml_hw_model.py (the Q8.24 model): integer-only
#  arithmetic, identical shifts/masks/saturation logic to the Verilog,
#  no math.exp / math.log shortcuts anywhere in the computation path.
#
#  Modules mirrored:
#    mitchell_log2_q88.v  -> mitchell_log2(x_raw)
#    mitchell_exp2_q88.v  -> mitchell_exp2(x_raw)
#    eml_tile_q88.v       -> eml_tile(x_raw, y_raw)
#    eml_mul_q88.v        -> eml_mul(a_raw, b_raw)
#
#  All inputs/outputs are raw 16-bit two's-complement integers (Q8.8).
# =============================================================================

W = 16
F = 8
SCALE = 1 << F             # 256
MASK16 = (1 << 16) - 1


def q88(val: float) -> int:
    """Encode a Python float to raw Q8.8 (unsigned 16-bit container)."""
    raw = round(val * SCALE)
    raw = max(-(1 << 15), min((1 << 15) - 1, raw))
    return raw & MASK16


def fq88(raw: int) -> float:
    """Decode raw Q8.8 (unsigned 16-bit container) to a Python float."""
    raw &= MASK16
    if raw >= (1 << 15):
        raw -= 1 << 16
    return raw / SCALE


def _sign_extend(val: int, bits: int) -> int:
    val &= (1 << bits) - 1
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val


def _to_u16(val: int) -> int:
    return val & MASK16


# =============================================================================
#  mitchell_log2(x_raw) -> (y_raw, ovf)   mirrors mitchell_log2_q88.v
# =============================================================================

def mitchell_log2(x_raw: int):
    x_raw &= MASK16

    if x_raw == 0:
        return (1 << 15), 1

    msb_pos = x_raw.bit_length() - 1

    e_fp = (msb_pos - F) << F

    shift_amt = W - 1 - msb_pos
    xs = (x_raw << shift_amt) & MASK16

    f_raw = (xs >> (W - 1 - F)) & ((1 << F) - 1)

    inv_f = (~f_raw) & ((1 << F) - 1)
    prod = f_raw * inv_f

    p11 = (prod << 3) + (prod << 1) + prod

    delta = (p11 >> (F + 5)) & ((1 << F) - 1)

    f_wide = f_raw + delta
    if f_wide & (1 << F):
        f_corr = (1 << F) - 1
    else:
        f_corr = f_wide & ((1 << F) - 1)

    y_raw = e_fp + f_corr
    return (y_raw & MASK16), 0


# =============================================================================
#  mitchell_exp2(x_raw) -> y_raw   mirrors mitchell_exp2_q88.v
# =============================================================================

def mitchell_exp2(x_raw: int) -> int:
    x_signed = _sign_extend(x_raw, W)

    INT = W - F   # 8

    e = _sign_extend((x_signed >> F) & ((1 << INT) - 1), INT)
    f = x_signed & ((1 << F) - 1)

    inv_f = (~f) & ((1 << F) - 1)
    prod = f * inv_f
    p11 = (prod << 3) + (prod << 1) + prod
    delta = (p11 >> (F + 5)) & ((1 << F) - 1)

    mant = ((1 << F) | f) - delta

    wide_base = mant << W

    rsh = 16 - e   # W=16

    TWO_W = 2 * W
    if rsh < 0:
        return (1 << W) - 1
    if rsh >= TWO_W:
        return 0

    wide = wide_base >> rsh

    if wide >> W:
        return (1 << W) - 1
    return wide & MASK16


# =============================================================================
#  eml_tile(x_raw, y_raw) -> (out_raw, ovf)   mirrors eml_tile_q88.v
# =============================================================================

LOG2E_Q88 = 0x0171     # = round(log2(e) * 256) = 369
LN2_Q88   = 0x00B1     # = round(ln(2)   * 256) = 177


def _q88_mul_take_slice(a_signed: int, b_const: int):
    """Mirrors the FIXED eml_tile_q88.v: the wide product's top (W-F+1)
    bits must all be a valid sign extension of the chosen 16-bit window,
    or the truncation would silently wrap (the bug found via the softmax
    max-trick's extreme-logit test: x=-100 wrapped to +111.86 instead of
    saturating to -128.0). Returns (result_raw, overflow_flag)."""
    wide = a_signed * b_const                      # 2W-bit signed product
    window_bits = W - F + 1                        # 9 redundant top bits for W=16,F=8
    top = (wide >> (F + W - 1)) & ((1 << window_bits) - 1)
    all_ones = (1 << window_bits) - 1
    overflowed = top != 0 and top != all_ones
    if overflowed:
        sign = (wide >> (2 * W - 1)) & 1
        result = (1 << (W - 1)) if sign else ((1 << (W - 1)) - 1)
    else:
        result = (wide >> F) & MASK16
    return result, (1 if overflowed else 0)


def eml_tile(x_raw: int, y_raw: int):
    x_signed = _sign_extend(x_raw, W)

    x2_raw, x2_ovf = _q88_mul_take_slice(x_signed, LOG2E_Q88)
    exp_x = mitchell_exp2(x2_raw)

    log2_y_raw, log_ovf = mitchell_log2(y_raw)
    log2_y_signed = _sign_extend(log2_y_raw, W)
    ln_y_raw, lny_ovf = _q88_mul_take_slice(log2_y_signed, LN2_Q88)
    ln_y_signed = _sign_extend(ln_y_raw, W)

    # (W+1)-bit two's-complement wraparound, exactly like the Verilog
    # diff[W] / diff[W-1] decode -- this is the saturation bug class
    # caught during Q8.24 cross-validation, so the fix is applied here
    # from the start rather than re-discovered.
    diff_full = (exp_x - ln_y_signed) & ((1 << (W + 1)) - 1)

    diff_W   = (diff_full >> W) & 1
    diff_Wm1 = (diff_full >> (W - 1)) & 1

    if diff_W != diff_Wm1:
        sub_ovf = 1
        if diff_W:
            out_raw = 1 << (W - 1)                # NEG_SAT
        else:
            out_raw = ((1 << (W - 1)) - 1)          # POS_SAT
    else:
        sub_ovf = 0
        out_raw = diff_full & MASK16

    ovf = log_ovf | x2_ovf | lny_ovf | sub_ovf
    return out_raw, ovf


# =============================================================================
#  eml_mul(a_raw, b_raw) -> (out_raw, ovf)   mirrors eml_mul_q88.v
# =============================================================================

def eml_mul(a_raw: int, b_raw: int):
    a_signed = _sign_extend(a_raw, W)
    b_signed = _sign_extend(b_raw, W)

    sign_a = 1 if a_signed < 0 else 0
    sign_b = 1 if b_signed < 0 else 0
    sign_out = sign_a ^ sign_b

    abs_a = (-a_signed) if sign_a else a_signed
    abs_b = (-b_signed) if sign_b else b_signed

    zero_a = (a_signed == 0)
    zero_b = (b_signed == 0)

    if zero_a or zero_b:
        return 0, 0

    log2_a_raw, ovf_la = mitchell_log2(_to_u16(abs_a))
    log2_b_raw, ovf_lb = mitchell_log2(_to_u16(abs_b))

    if ovf_la or ovf_lb:
        return 0, 1

    log2_a_signed = _sign_extend(log2_a_raw, W)
    log2_b_signed = _sign_extend(log2_b_raw, W)

    log2_sum = log2_a_signed + log2_b_signed
    SIGNED_MIN = -(1 << (W - 1))
    SIGNED_MAX = (1 << (W - 1)) - 1
    if log2_sum > SIGNED_MAX:
        log2_sum_clamped = SIGNED_MAX
    elif log2_sum < SIGNED_MIN:
        log2_sum_clamped = SIGNED_MIN
    else:
        log2_sum_clamped = log2_sum

    abs_out = mitchell_exp2(_to_u16(log2_sum_clamped))
    ovf_exp = 1 if abs_out == MASK16 else 0

    signed_out = (-abs_out) if sign_out else abs_out
    return _to_u16(signed_out), ovf_exp


if __name__ == "__main__":
    print("eml_tile(0, 1):")
    out_raw, ovf = eml_tile(q88(0.0), q88(1.0))
    print(f"  out = {fq88(out_raw):.6f}   ovf = {ovf}   (expect ~1.0 exact)")

    print("eml_tile(1, 1):")
    out_raw, ovf = eml_tile(q88(1.0), q88(1.0))
    print(f"  out = {fq88(out_raw):.6f}   ovf = {ovf}   (expect ~2.71828, hw approx)")

    print("eml_mul(2.0, 3.0):")
    out_raw, ovf = eml_mul(q88(2.0), q88(3.0))
    print(f"  out = {fq88(out_raw):.6f}   ovf = {ovf}   (expect ~6.0, hw approx)")

    print("eml_tile(1, 0):")
    out_raw, ovf = eml_tile(q88(1.0), 0)
    print(f"  out = {fq88(out_raw):.6f}   ovf = {ovf}   (expect ovf=1)")
