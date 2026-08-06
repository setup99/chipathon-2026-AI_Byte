// ============================================================
//  eml_sqrt_q88_shared.v
//  sqrt(x)  in Q8.8 -- FSM, two EML passes
//
//  SHARED-TILE VARIANT -- see eml_sigmoid_q88_shared.v for the
//  rationale. Identical FSM/logic to eml_sqrt_q88.v; only the
//  tile's physical location changed.
// ============================================================
`timescale 1ns/1ps

module eml_sqrt_q88_shared #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire             clk, rst, start,
    input  wire        [W-1:0] x_in,   // unsigned Q8.8, must be > 0
    output reg  signed [W-1:0] result,
    output reg                 valid,
    output reg                 ovf,

    output wire signed [W-1:0] eml_x_out,
    output wire        [W-1:0] eml_y_out,
    input  wire signed [W-1:0] eml_out_in,
    input  wire                 eml_ovf_in
);
    localparam signed [W-1:0] Q88_ONE  = 16'sh0100;  // 1.0
    localparam signed [W-1:0] Q88_ZERO = 16'sh0000;  // 0.0

    reg  signed [W-1:0] eml_x;
    reg         [W-1:0] eml_y;
    assign eml_x_out = eml_x;
    assign eml_y_out = eml_y;
    wire signed [W-1:0] eml_out = eml_out_in;
    wire                eml_ovf = eml_ovf_in;

    // ── digital subtract: ln(x) = 1 - (1 - ln x) ──────────────
    wire signed [W:0] sub_wide = $signed({Q88_ONE[W-1],Q88_ONE})
                                - $signed({eml_out[W-1],eml_out});
    wire signed [W-1:0] ln_x   =
        (sub_wide[W] != sub_wide[W-1])
        ? (sub_wide[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : sub_wide[W-1:0];

    // ── halving: ln(x)/2 via arithmetic right-shift, free in HW ──
    wire signed [W-1:0] half_ln_x = ln_x >>> 1;

    reg err_acc;

    localparam S_IDLE=2'd0, S_P1=2'd1, S_HALF=2'd2, S_P2=2'd3;
    reg [1:0] state;

    always @(posedge clk) begin
        if (rst) begin
            state<=S_IDLE; result<=0; valid<=0; ovf<=0;
            eml_x<=0; eml_y<=Q88_ONE[W-1:0]; err_acc<=0;
        end else begin
            valid <= 0;
            case (state)
                S_IDLE: begin
                    err_acc <= 0;
                    if (start) begin
                        eml_x <= Q88_ZERO;
                        eml_y <= x_in;
                        state <= S_P1;
                    end
                end
                // eml_out = 1 - ln(x)  (settled this cycle)
                S_P1: begin
                    err_acc <= eml_ovf;
                    state   <= S_HALF;
                end
                // ln_x and half_ln_x are combinational from eml_out above;
                // latch the halved value and drive pass 2
                S_HALF: begin
                    eml_x <= half_ln_x;
                    eml_y <= Q88_ONE[W-1:0];
                    state <= S_P2;
                end
                // eml_out = exp(ln(x)/2) = sqrt(x)
                S_P2: begin
                    result <= eml_out;
                    ovf    <= err_acc | eml_ovf;
                    valid  <= 1;
                    state  <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
