// ============================================================
//  eml_tanh_q88_shared.v
//  tanh(x) = 2*sigma(2x) - 1  in Q8.8 -- 7-state FSM
//
//  SHARED-TILE VARIANT -- see eml_sigmoid_q88_shared.v for the
//  rationale. Identical FSM/logic to eml_tanh_q88.v; only the
//  tile's physical location changed (external request/response
//  instead of a private u_eml instance).
// ============================================================
`timescale 1ns/1ps

module eml_tanh_q88_shared #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire             clk, rst_n, start,
    input  wire signed [W-1:0] x_in,
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

    // ── saturating ALU, shared by S_ADD and S_SUB ─────────────
    reg  signed [W-1:0] alu_a, alu_b;
    reg                 alu_sel;   // 0=add  1=sub
    wire signed [W:0]   alu_wide = alu_sel
        ? ($signed({alu_a[W-1],alu_a}) - $signed({alu_b[W-1],alu_b}))
        : ($signed({alu_a[W-1],alu_a}) + $signed({alu_b[W-1],alu_b}));
    wire signed [W-1:0] alu_out  =
        (alu_wide[W] != alu_wide[W-1])
        ? (alu_wide[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : alu_wide[W-1:0];

    // ── final rescale: 2*sigma(2x) - 1, computed combinationally
    //    from eml_out during S_P3 (the same cycle eml_out=sigma(2x)
    //    settles), then registered in S_SCALE ──────────────────
    wire signed [W:0]   doubled_sig = {eml_out, 1'b0};   // sigma << 1, one extra guard bit
    wire signed [W:0]   scale_wide  = doubled_sig - {{1{Q88_ONE[W-1]}}, Q88_ONE};
    wire signed [W-1:0] scale_out   =
        (scale_wide[W] != scale_wide[W-1])
        ? (scale_wide[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : scale_wide[W-1:0];

    reg signed [W-1:0] neg_ln_y2;
    reg                err_acc;

    localparam S_IDLE=3'd0, S_P1=3'd1, S_ADD=3'd2, S_P2=3'd3,
               S_SUB=3'd4,  S_P3=3'd5, S_SCALE=3'd6;
    reg [2:0] state;

    always @(posedge clk) begin
        if (!rst_n) begin
            state<=S_IDLE; result<=0; valid<=0; ovf<=0;
            eml_x<=0; eml_y<=Q88_ONE[W-1:0];
            alu_a<=0; alu_b<=0; alu_sel<=0;
            neg_ln_y2<=0; err_acc<=0;
        end else begin
            valid <= 0;
            case (state)
                S_IDLE: begin
                    err_acc<=0;
                    if (start) begin
                        eml_x <= -(x_in <<< 1);
                        eml_y <= Q88_ONE[W-1:0];
                        state <= S_P1;
                    end
                end
                // eml_out = e^-2x
                S_P1: begin
                    err_acc <= eml_ovf;
                    alu_a <= Q88_ONE; alu_b <= eml_out; alu_sel <= 0;
                    state <= S_ADD;
                end
                // alu_out = 1 + e^-2x = Y2
                S_ADD: begin
                    err_acc <= err_acc | (alu_wide[W]!=alu_wide[W-1]);
                    eml_x <= Q88_ZERO; eml_y <= alu_out[W-1:0];
                    state <= S_P2;
                end
                // eml_out = 1 - ln(Y2)
                S_P2: begin
                    err_acc <= err_acc | eml_ovf;
                    alu_a <= eml_out; alu_b <= Q88_ONE; alu_sel <= 1;
                    state <= S_SUB;
                end
                // alu_out = -ln(Y2)
                S_SUB: begin
                    neg_ln_y2 <= alu_out;
                    err_acc <= err_acc | (alu_wide[W]!=alu_wide[W-1]);
                    eml_x <= alu_out; eml_y <= Q88_ONE[W-1:0];
                    state <= S_P3;
                end
                // eml_out = exp(-ln Y2) = 1/Y2 = sigma(2x)
                S_P3: begin
                    err_acc <= err_acc | eml_ovf;
                    state   <= S_SCALE;
                end
                // scale_out settled last cycle from eml_out; register it
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
