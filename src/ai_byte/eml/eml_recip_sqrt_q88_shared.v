// ============================================================
//  eml_recip_sqrt_q88_shared.v
//  1/x     in Q8.8 -- mode=0
//  sqrt(x) in Q8.8 -- mode=1
//  ONE 4-state FSM shared by both, with a single subtractor.
//
//  Both functions are structurally the same 3-step LNS pipeline:
//    pass 1:  eml_out = 1 - ln(x)
//    scale :  a trivial linear transform of eml_out
//    pass 2:  eml_out = exp(scale) = the answer
//
//  The two differ only in the middle step:
//    recip: alu_out = eml_out - 1        = -ln(x)          (no shift)
//    sqrt : alu_out = 1 - eml_out        =  ln(x), then >>>1 for /2
//
//  recip's (eml_out - 1) and sqrt's (1 - eml_out) are exact negatives
//  of each other -- rather than deriving one from the other's result
//  post-saturation (which risks the saturating-subtract nonlinearity
//  disagreeing with the original bit-exact behavior at the extremes),
//  the shared subtractor takes its operand ORDER from `mode` instead,
//  reproducing each original module's arithmetic exactly:
//
//    alu_a <= mode ? Q88_ONE : eml_out;
//    alu_b <= mode ? eml_out : Q88_ONE;
//
//  then the S_SUB->S_P2 transition applies sqrt's extra >>>1 only
//  when mode=1, exactly like eml_sqrt_q88_shared.v's S_HALF state --
//  folded into the same cycle rather than a separate state, since
//  recip never needed that state at all.
//
//  Replaces two independent FSMs (eml_recip_q88_shared.v,
//  eml_sqrt_q88_shared.v -- 200 + 167 = 367 cells measured) with one.
// ============================================================
`timescale 1ns/1ps

module eml_recip_sqrt_q88_shared #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire             clk, start,
    input  wire             rst_n,   // synchronous, active-low
    input  wire              mode,   // 0 = recip, 1 = sqrt
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

    // ── shared subtractor: operand order picked by mode ────────
    reg  signed [W-1:0] alu_a, alu_b;
    wire signed [W:0]   alu_wide = $signed({alu_a[W-1],alu_a})
                                  - $signed({alu_b[W-1],alu_b});
    wire signed [W-1:0] alu_out  =
        (alu_wide[W] != alu_wide[W-1])
        ? (alu_wide[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : alu_wide[W-1:0];

    reg err_acc;
    reg mode_r;   // captured at S_IDLE, used at S_SUB's half-shift

    localparam S_IDLE=2'd0, S_P1=2'd1, S_SUB=2'd2, S_P2=2'd3;
    reg [1:0] state;

    always @(posedge clk) begin
        if (!rst_n) begin
            state<=S_IDLE; result<=0; valid<=0; ovf<=0;
            eml_x<=0; eml_y<=Q88_ONE[W-1:0];
            alu_a<=0; alu_b<=0; err_acc<=0; mode_r<=0;
        end else begin
            valid <= 0;
            case (state)
                S_IDLE: begin
                    err_acc <= 0;
                    if (start) begin
                        mode_r <= mode;
                        eml_x  <= Q88_ZERO;
                        eml_y  <= x_in;
                        state  <= S_P1;
                    end
                end
                // eml_out = 1 - ln(x)
                S_P1: begin
                    err_acc <= eml_ovf;
                    // recip: alu_out = eml_out - 1 = -ln(x)
                    // sqrt : alu_out = 1 - eml_out =  ln(x)
                    alu_a <= mode_r ? Q88_ONE : eml_out;
                    alu_b <= mode_r ? eml_out : Q88_ONE;
                    state <= S_SUB;
                end
                // alu_out settled; sqrt halves it here (folded into
                // this transition instead of a separate S_HALF state)
                S_SUB: begin
                    err_acc <= err_acc | (alu_wide[W]!=alu_wide[W-1]);
                    eml_x <= mode_r ? (alu_out >>> 1) : alu_out;
                    eml_y <= Q88_ONE[W-1:0];
                    state <= S_P2;
                end
                // eml_out = exp(-ln x) = 1/x   (or exp(ln(x)/2) = sqrt(x))
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
