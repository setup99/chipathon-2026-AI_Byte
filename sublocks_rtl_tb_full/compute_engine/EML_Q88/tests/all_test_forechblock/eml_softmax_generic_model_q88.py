# =============================================================================
#  eml_softmax_generic_model_q88.py
#  Bit-exact Python model of eml_softmax_q88's FSM, generalized to any N,
#  built the same way eml_hw_model_q88.py was: same shifts/masks/saturation
#  logic as the RTL, reusing the already-verified eml_tile() primitive.
# =============================================================================

from eml_hw_model_q88 import eml_tile, q88, fq88, _sign_extend, _to_u16, W, MASK16


def _sat_alu(a_signed: int, b_signed: int, sub: bool):
    """Mirrors: alu_wide = sign-extended (W+1)-bit add/sub, then the
    alu_wide[W]!=alu_wide[W-1] saturation check exactly as in the RTL."""
    wide = (a_signed - b_signed) if sub else (a_signed + b_signed)
    wide &= (1 << (W + 1)) - 1
    bW = (wide >> W) & 1
    bWm1 = (wide >> (W - 1)) & 1
    if bW != bWm1:
        ovf = 1
        out = (1 << (W - 1)) if bW else ((1 << (W - 1)) - 1)
    else:
        ovf = 0
        out = wide & MASK16
    return out, ovf


def eml_softmax(z_raw_list, N):
    assert len(z_raw_list) == N
    # z_buf in the RTL is declared `reg signed [W-1:0]`, so every use of a
    # stored z value in arithmetic is automatically sign-extended by
    # Verilog. Do that explicitly here -- q88() returns the raw *unsigned*
    # container, so skipping this step silently corrupts every negative
    # logit's arithmetic (caught via a stage-by-stage trace, not assumed).
    z_raw_list = [_sign_extend(z, W) for z in z_raw_list]
    err = 0

    # Max-trick: 8-way max tree + parallel saturating subtractors in the
    # RTL, done here as max() over the N active values (no masking needed
    # since this list is already exactly N long, unlike the RTL's fixed
    # 8-wide bus with inactive slots masked to a sentinel). This step is
    # NOT optional for bit-exactness: even though softmax is
    # mathematically shift-invariant, Mitchell's approximation error
    # depends on the actual quantized operating point, so the model must
    # shift by the same max_z the RTL does, not just produce the same
    # final answer through a different (also "correct") path.
    max_z = max(z_raw_list)
    z_shift = []
    for z in z_raw_list:
        raw, ovf = _sat_alu(z, max_z, sub=True)
        z_shift.append(_sign_extend(raw, W))
        err |= ovf
    z_raw_list = z_shift

    # Pass 1 xN: EML(zi, 1.0) -> e^zi
    exp_buf = []
    for z in z_raw_list:
        out, ovf = eml_tile(_to_u16(z), q88(1.0))
        exp_buf.append(_sign_extend(out, W))
        err |= ovf

    # Digital: S = sum(e^zj), sequential saturating adds (idx starts at 1)
    sum_acc = exp_buf[0]
    for i in range(1, N):
        raw, ovf = _sat_alu(sum_acc, exp_buf[i], sub=False)
        sum_acc = _sign_extend(raw, W)
        err |= ovf

    # Pass 2 x1: EML(0, S) -> 1 - ln(S)
    eml_out, ovf = eml_tile(_to_u16(0), _to_u16(sum_acc))
    err |= ovf
    raw, ovf = _sat_alu(q88(1.0), _sign_extend(eml_out, W), sub=True)
    ln_s = _sign_extend(raw, W)
    err |= ovf

    # Pass 3 xN: EML(zi - ln_s, 1.0) -> e^zi / S
    result = []
    for i in range(N):
        raw, ovf = _sat_alu(z_raw_list[i], ln_s, sub=True)
        tgt = _sign_extend(raw, W)
        err |= ovf
        out, ovf = eml_tile(_to_u16(tgt), q88(1.0))
        result.append(_sign_extend(out, W))
        err |= ovf

    return result, err


if __name__ == "__main__":
    for N in range(2, 9):
        zs = [1.0, 0.5, -0.5, -1.0, 2.0, 0.25, -2.0, 1.5][:N]
        raws = [q88(v) for v in zs]
        res, ovf = eml_softmax(raws, N)
        vals = [round(fq88(r), 5) for r in res]
        print(f"N={N}  z={zs}  softmax~={vals}  sum={sum(vals):.5f}  ovf={ovf}")
