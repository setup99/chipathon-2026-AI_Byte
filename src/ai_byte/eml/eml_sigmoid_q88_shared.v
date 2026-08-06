// ============================================================
//  eml_sigmoid_q88_shared.v
//  sigma(x) = 1/(1+e^-x)  in Q8.8 -- 6-state FSM
//
//  SHARED-TILE VARIANT: identical FSM/logic to eml_sigmoid_q88.v,
//  but no longer owns a private eml_tile_q88 instance. Instead it
//  exposes the tile request (eml_x_out/eml_y_out) and expects the
//  tile response (eml_out_in/eml_ovf_in) to be supplied externally
//  -- by a single tile shared across all sub-blocks at the wrapper
//  level (see eml_wrapper_q88_shared.v). This is the same "share
//  one eml_tile across multiple sequential passes" trick this
//  module already used internally (one tile, 3 EML calls per
//  transaction) -- just applied one level higher, across blocks
//  instead of within one.
//
//  Every state, every register, every cycle count is byte-for-byte
//  identical to eml_sigmoid_q88.v; only the tile's physical location
//  changed. See the original file for the full derivation/comments.
// ============================================================
`timescale 1ns/1ps

module eml_sigmoid_q88_shared #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire             clk, rst_n, start,
    input  wire signed [W-1:0] x_in,
    output reg  signed [W-1:0] result,
    output reg                 valid,
    output reg                 ovf,

    // shared-tile request/response (replaces the private u_eml instance)
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

    reg  signed [W-1:0] alu_a, alu_b;
    reg                 alu_sel;   // 0=add  1=sub
    wire signed [W:0]   alu_wide = alu_sel
        ? ($signed({alu_a[W-1],alu_a}) - $signed({alu_b[W-1],alu_b}))
        : ($signed({alu_a[W-1],alu_a}) + $signed({alu_b[W-1],alu_b}));
    wire signed [W-1:0] alu_out  =
        (alu_wide[W] != alu_wide[W-1])
        ? (alu_wide[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : alu_wide[W-1:0];

    reg err_acc;

    localparam S_IDLE=3'd0, S_P1=3'd1, S_ADD=3'd2, S_P2=3'd3,
               S_SUB=3'd4,  S_P3=3'd5, S_DONE=3'd6;
    reg [2:0] state;

    always @(posedge clk) begin
        if (!rst_n) begin
            state<=S_IDLE; result<=0; valid<=0; ovf<=0;
            eml_x<=0; eml_y<=Q88_ONE[W-1:0];
            alu_a<=0; alu_b<=0; alu_sel<=0; err_acc<=0;
        end else begin
            valid <= 0;
            case (state)
                S_IDLE: begin
                    err_acc <= 0;
                    if (start) begin
                        eml_x <= -x_in;
                        eml_y <= Q88_ONE[W-1:0];
                        state <= S_P1;
                    end
                end
                // eml_out = e^-x
                S_P1: begin
                    err_acc <= eml_ovf;
                    alu_a <= Q88_ONE; alu_b <= eml_out; alu_sel <= 0;
                    state <= S_ADD;
                end
                // alu_out = 1 + e^-x = Y
                S_ADD: begin
                    err_acc <= err_acc | (alu_wide[W]!=alu_wide[W-1]);
                    eml_x <= Q88_ZERO; eml_y <= alu_out[W-1:0];
                    state <= S_P2;
                end
                // eml_out = 1 - ln(Y)
                S_P2: begin
                    err_acc <= err_acc | eml_ovf;
                    alu_a <= eml_out; alu_b <= Q88_ONE; alu_sel <= 1;
                    state <= S_SUB;
                end
                // alu_out = -ln(Y)
                S_SUB: begin
                    err_acc <= err_acc | (alu_wide[W]!=alu_wide[W-1]);
                    eml_x <= alu_out; eml_y <= Q88_ONE[W-1:0];
                    state <= S_P3;
                end
                // eml_out = exp(-ln Y) = 1/Y = sigma(x)
                S_P3: begin
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
