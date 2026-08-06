// ============================================================
//  mitchell_exp2_q88.v
//  Lightweight Mitchell 2^x for Q8.8 fixed point
//
//  Format: Q8.8  W=16  F=8
//
//  2^f ~ (1+f) - f*(1-f)*11/32     max abs error 0.0039
//  Same coefficient as Q8.24 -- verified by sweep, error shape
//  is a property of f in [0,1), not of F.
//
//  Hardware: identical structure to the Q8.24 design, just at
//  half the word width.
//
//  Ports
//  -----
//  x   [W-1:0]  signed   Q8.8  (binary exponent)
//  y   [W-1:0]  unsigned Q8.8  result = 2^x_real
// ============================================================
`timescale 1ns/1ps

module mitchell_exp2_q88 #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire signed [W-1:0]  x,
    output reg         [W-1:0]  y
);
    localparam INT = W - F;   // 8

    wire signed [INT-1:0] e = x[W-1:F];
    wire        [F-1:0]   f = x[F-1:0];

    // ── correction: delta = f*(1-f)*11/32  (SUBTRACT) ────────
    wire [F-1:0]   inv_f = ~f;
    wire [2*F-1:0] prod  = f * inv_f;

    wire [2*F+3:0] p11 = {prod, 3'b0}
                       + {1'b0, prod, 1'b0}
                       + {2'b0, prod};

    wire [F-1:0] delta = {{1{1'b0}}, p11[2*F+3 : F+5]};

    wire [F:0] mant = {1'b1, f} - {1'b0, delta};

    // ── barrel shift ──────────────────────────────────────────
    wire [2*W-1:0]  wide_base = {{(W-F-1){1'b0}}, mant, {W{1'b0}}};
    wire signed [8:0] e_w9    = {{(9-INT){e[INT-1]}}, e};
    wire signed [8:0] rsh     = 9'sd16 - e_w9;     // W=16

    reg [2*W-1:0] wide;
    always @(*) begin
        if (rsh < 0)         y = {W{1'b1}};
        else if (rsh >= 2*W) y = {W{1'b0}};
        else begin
            wide = wide_base >> rsh;
            y    = (|wide[2*W-1:W]) ? {W{1'b1}} : wide[W-1:0];
        end
    end
endmodule
