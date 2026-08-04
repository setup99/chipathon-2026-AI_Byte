// ============================================================
//  mitchell_log2_q88.v
//  Lightweight Mitchell log2 for Q8.8 fixed point
//
//  Format: Q8.8  W=16  F=8
//    real = signed_int / 256
//    range: -128 to +127.996
//    resolution: 1/256 = 3.906e-3
//
//  Same 11/32 correction coefficient as the Q8.24 design (the
//  optimum depends only on f in [0,1), not on F -- verified by
//  numerical sweep before writing this file).
//
//  log2(1+f) ~ f + f*(1-f)*11/32     max abs error 0.0081
//
//  Hardware:
//    inv_f  = ~f                        [F-bit bitwise NOT]
//    prod   = f * inv_f                  [F x F = 16-bit multiply]
//    p11    = prod*8 + prod*2 + prod     [shift-add, no 2nd multiply]
//    delta  = p11 >> (F+5)
//    f_corr = f + delta  (ADD: Mitchell underestimates log2)
//
//  Ports
//  -----
//  x   [W-1:0]  unsigned Q8.8  (strictly positive)
//  y   [W-1:0]  signed   Q8.8  result = log2(x)
//  ovf          1 when x = 0 (ln undefined)
// ============================================================
`timescale 1ns/1ps

module mitchell_log2_q88 #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire [W-1:0]   x,
    output reg  [W-1:0]   y,
    output reg            ovf
);
    localparam INT = W - F;   // 8

    // ── LZD: find position of MSB ─────────────────────────────
    reg [$clog2(W)-1:0] msb_pos;
    integer k;
    always @(*) begin
        msb_pos = 0;
        for (k = 0; k < W; k = k + 1)
            if (x[k]) msb_pos = k;
    end

    // ── integer exponent in Q8.8 ──────────────────────────────
    wire signed [W-1:0] e_fp =
        ($signed({{(W-$clog2(W)){1'b0}}, msb_pos}) - $signed(F[W-1:0])) <<< F;

    // ── raw fractional mantissa f (F bits) ────────────────────
    reg [W-1:0] xs;
    always @(*) xs = x << (W - 1 - msb_pos);
    wire [F-1:0] f_raw = xs[W-2 -: F];

    // ── correction: delta = f*(1-f)*11/32 ────────────────────
    wire [F-1:0]   inv_f = ~f_raw;
    wire [2*F-1:0] prod  = f_raw * inv_f;          // 16-bit product

    wire [2*F+3:0] p11 = {prod, 3'b0}
                       + {1'b0, prod, 1'b0}
                       + {2'b0, prod};

    wire [F-1:0] delta = {{1{1'b0}}, p11[2*F+3 : F+5]};

    wire [F:0] f_wide  = {1'b0, f_raw} + {1'b0, delta};
    wire [F-1:0] f_corr = f_wide[F] ? {F{1'b1}} : f_wide[F-1:0];

    // ── result ────────────────────────────────────────────────
    always @(*) begin
        if (x == 0) begin
            y   = {1'b1, {(W-1){1'b0}}};
            ovf = 1;
        end else begin
            y   = e_fp + $signed({{INT{1'b0}}, f_corr});
            ovf = 0;
        end
    end

endmodule
