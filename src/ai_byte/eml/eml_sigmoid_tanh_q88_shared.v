// ============================================================
//  eml_sigmoid_tanh_q88_shared.v
//  sigma(x) = 1/(1+e^-x)          -- mode=0
//  tanh(x)  = 2*sigma(2x) - 1     -- mode=1
//  in Q8.8 -- ONE 7-state FSM shared by both functions.
//
//  tanh(x) = 2*sigma(2x) - 1 is the only relationship between the
//  two functions this design needs: every state through S_P3 is
//  byte-for-byte identical arithmetic for both modes (same ALU,
//  same tile-call sequence, same err_acc accumulation) -- the only
//  two places mode actually changes anything are:
//
//    (1) S_IDLE's initial eml_x: -x_in (sigmoid) vs -(x_in<<<1) (tanh)
//    (2) after S_P3 settles eml_out = sigma(x) or sigma(2x): sigmoid
//        is already done (skip straight to S_IDLE with result=eml_out),
//        tanh needs one more state (S_SCALE) to register
//        2*eml_out - 1
//
//  This replaces two full independent FSMs (eml_sigmoid_q88_shared.v,
//  eml_tanh_q88_shared.v -- 520 + 592 = 1,112 cells measured) with one
//  that pays for the shared ALU/state register once. `mode` is a
//  plain combinational input, sampled only during the same cycle
//  `start` is asserted (exactly like x_in already was) -- there is no
//  need to register it separately since the FSM doesn't look at it
//  again until the next S_IDLE+start.
// ============================================================
`timescale 1ns/1ps

module eml_sigmoid_tanh_q88_shared #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire             clk, start,
    input  wire             rst_n,   // synchronous, active-low
    input  wire              mode,   // 0 = sigmoid, 1 = tanh
    input  wire signed [W-1:0] x_in,
    output reg  signed [W-1:0] result,
    output reg                 valid,
    output reg                 ovf,

    // shared-tile request/response
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

    // ── saturating ALU, shared by S_ADD and S_SUB (both modes) ──
    reg  signed [W-1:0] alu_a, alu_b;
    reg                 alu_sel;   // 0=add  1=sub
    wire signed [W:0]   alu_wide = alu_sel
        ? ($signed({alu_a[W-1],alu_a}) - $signed({alu_b[W-1],alu_b}))
        : ($signed({alu_a[W-1],alu_a}) + $signed({alu_b[W-1],alu_b}));
    wire signed [W-1:0] alu_out  =
        (alu_wide[W] != alu_wide[W-1])
        ? (alu_wide[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : alu_wide[W-1:0];

    // ── tanh-only final rescale: 2*sigma(2x) - 1, computed
    //    combinationally from eml_out during S_P3 (the same cycle
    //    eml_out=sigma(2x) settles), then registered in S_SCALE --
    //    dark/unused logic when mode=0, but far cheaper than a
    //    second copy of the whole FSM ──────────────────────────
    wire signed [W:0]   doubled_sig = {eml_out, 1'b0};
    wire signed [W:0]   scale_wide  = doubled_sig - {{1{Q88_ONE[W-1]}}, Q88_ONE};
    wire signed [W-1:0] scale_out   =
        (scale_wide[W] != scale_wide[W-1])
        ? (scale_wide[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : scale_wide[W-1:0];

    reg err_acc;
    reg mode_r;   // captured at S_IDLE, used at S_P3/S_SCALE branch points

    localparam S_IDLE=3'd0, S_P1=3'd1, S_ADD=3'd2, S_P2=3'd3,
               S_SUB=3'd4,  S_P3=3'd5, S_SCALE=3'd6;
    reg [2:0] state;

    always @(posedge clk) begin
        if (!rst_n) begin
            state<=S_IDLE; result<=0; valid<=0; ovf<=0;
            eml_x<=0; eml_y<=Q88_ONE[W-1:0];
            alu_a<=0; alu_b<=0; alu_sel<=0; err_acc<=0; mode_r<=0;
        end else begin
            valid <= 0;
            case (state)
                S_IDLE: begin
                    err_acc <= 0;
                    if (start) begin
                        mode_r <= mode;
                        eml_x  <= mode ? -(x_in <<< 1) : -x_in;
                        eml_y  <= Q88_ONE[W-1:0];
                        state  <= S_P1;
                    end
                end
                // eml_out = e^-x (sigmoid) or e^-2x (tanh)
                S_P1: begin
                    err_acc <= eml_ovf;
                    alu_a <= Q88_ONE; alu_b <= eml_out; alu_sel <= 0;
                    state <= S_ADD;
                end
                // alu_out = 1 + e^-x = Y  (or 1+e^-2x = Y2)
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
                // eml_out = exp(-ln Y) = 1/Y = sigma(x) or sigma(2x)
                S_P3: begin
                    if (mode_r) begin
                        err_acc <= err_acc | eml_ovf;
                        state   <= S_SCALE;
                    end else begin
                        result <= eml_out;
                        ovf    <= err_acc | eml_ovf;
                        valid  <= 1;
                        state  <= S_IDLE;
                    end
                end
                // tanh only: scale_out settled last cycle from eml_out
                S_SCALE: begin
                    result <= scale_out;
                    ovf    <= err_acc | (scale_wide[W]!=scale_wide[W-1]);
                    valid  <= 1;
                    state  <= S_IDLE;
                end
                default: state <= S_IDLE;
            endcase
        end
    end
endmodule
