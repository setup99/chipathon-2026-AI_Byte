// ============================================================
//  eml_tile_q88.v
//  Lightweight EML gate: exp(x) - ln(y)  in Q8.8
//
//  Format: Q8.8  W=16  F=8
//    real = signed_int / 256
//    range: +/-128   resolution: 1/256 = 3.91e-3
//
//  Constants (scaled by 2^8 = 256):
//    log2(e) = 1.4426950408  ->  369  = 0x0171
//    ln(2)   = 0.6931471806  ->  177  = 0x00B1
//
//  BUGFIX (found via the softmax max-trick's extreme-logit test):
//  the x*LOG2E_Q88 and log2_y*LN2_Q88 scaling multiplies used to
//  truncate straight to a 16-bit window of the wide product with
//  NO overflow check. For |x| > 128/log2(e) =~ 88.7 (or |ln(y)|
//  large enough via log2_y*ln(2)), the true scaled value exceeds
//  Q8.8's +/-128 range, and a raw bit-slice WRAPS AROUND instead
//  of saturating -- e.g. x=-100.0 produced x2=+111.86 (should
//  have saturated to -128.0), which then fed mitchell_exp2_q88 a
//  wrong-signed, wrong-magnitude argument and produced out=+127.99
//  ovf=1 for what should have been out=~0, no overflow. Every
//  downstream stage was individually correct; only this
//  truncation was silently wrong. Fixed by checking the 9
//  redundant top bits of the 32-bit product are a valid sign
//  extension (same pattern as the final diff[W]!=diff[W-1]
//  check below, just widened since 9 bits are discarded here
//  instead of 1) and saturating on the true product's sign if not.
// ============================================================
`timescale 1ns/1ps

module eml_tile_q88 #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire signed [W-1:0]  x,      // signed Q8.8
    input  wire        [W-1:0]  y,      // unsigned Q8.8  (y > 0)
    output wire signed [W-1:0]  out,
    output wire                 ovf
);
    localparam signed [W-1:0] LOG2E_Q88 = 16'sh0171;  // 369
    localparam signed [W-1:0] LN2_Q88   = 16'sh00B1;  // 177

    // ── exp(x) ───────────────────────────────────────────────
    wire signed [2*W-1:0] x2_wide  = x * LOG2E_Q88;
    wire signed [W-1:0]   x2_trunc = x2_wide[F+W-1 : F];
    // redundant top (W-F+1) bits must all match the sign bit of
    // the chosen window, or the truncation silently wrapped
    wire                  x2_ovf   = ~(&x2_wide[2*W-1 -: (W-F+1)]) &
                                       (|x2_wide[2*W-1 -: (W-F+1)]);
    wire signed [W-1:0]   x2       = x2_ovf
        ? (x2_wide[2*W-1] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : x2_trunc;

    wire [W-1:0] exp_x;
    mitchell_exp2_q88 #(.W(W),.F(F)) u_exp (
        .x(x2), .y(exp_x)
    );

    // ── ln(y) ────────────────────────────────────────────────
    wire signed [W-1:0] log2_y;
    wire                log_ovf;
    mitchell_log2_q88 #(.W(W),.F(F)) u_log (
        .x(y), .y(log2_y), .ovf(log_ovf)
    );

    wire signed [2*W-1:0] lny_wide  = log2_y * LN2_Q88;
    wire signed [W-1:0]   lny_trunc = lny_wide[F+W-1 : F];
    wire                  lny_ovf   = ~(&lny_wide[2*W-1 -: (W-F+1)]) &
                                        (|lny_wide[2*W-1 -: (W-F+1)]);
    wire signed [W-1:0]   ln_y      = lny_ovf
        ? (lny_wide[2*W-1] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : lny_trunc;

    // ── subtract with (W+1)-bit two's-complement wraparound ──
    // (bit-exact saturation logic, decoded the same way as the
    //  Q8.24 design: compare diff[W] against diff[W-1], not a
    //  Python-style magnitude check)
    wire signed [W:0] diff = $signed({1'b0, exp_x})
                           - $signed({ln_y[W-1], ln_y});

    assign out = (diff[W] != diff[W-1])
                 ? (diff[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
                 : diff[W-1:0];

    assign ovf = log_ovf | x2_ovf | lny_ovf | (diff[W] != diff[W-1]);

endmodule
