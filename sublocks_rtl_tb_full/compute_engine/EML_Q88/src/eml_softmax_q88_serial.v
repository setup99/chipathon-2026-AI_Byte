// ============================================================
//  eml_softmax_q88_serial.v
//
//  FULLY-SERIAL VARIANT of eml_softmax_q88_rtn_shared.v:
//    - z_in  : single W-bit port + z_valid strobe (one logit
//              pushed per cycle, gaps allowed)
//    - result: single W-bit port + result_valid strobe (one
//              output emitted per cycle as it's computed)
//  instead of packed MAX_N*W-bit buses arriving/leaving all at
//  once. No packed bus port exists in this module at all.
//
//  Max-trick restructuring: the parallel 8-way max tree + 8
//  dedicated saturating subtractors are gone. Finding the max is
//  a single running-comparator reused N times during the load
//  phase (S_LOAD); the per-element zi-max_z shift reuses the same
//  shared ALU the rest of the FSM already uses (S_SHIFT/
//  S_SHIFT_LAT) -- the same "one unit, reused serially" principle
//  already applied to the EML tile itself.
//
//  Result streaming: S_FIN_LAT already computed one output
//  element per iteration in the parallel-output version (it just
//  wrote each one into a different slot of a packed register).
//  Here it drives `result`/`result_valid` directly instead --
//  no restructuring of the compute loop itself was needed, only
//  where each finished value goes.
//
//  `valid` is the overall transaction-complete pulse, coincident
//  with the LAST `result_valid` pulse (or with the immediate
//  n_err rejection path, which does not pulse result_valid at all
//  since there's no real output in that case).
//
//  Ports:
//    n_in         : 2..8, sampled with start
//    z_in         : W-bit signed, one logit
//    z_valid      : strobe, z_in captured while in S_LOAD
//    result       : W-bit signed, one output element
//    result_valid : strobe, pulses once per output element (n_in pulses total)
//    valid        : pulses on the final result_valid, or on n_err rejection
//    ovf, n_err   : same meaning as every other module in this family
//
//  Latency: measured, not just estimated -- see the accompanying
//  test output. Adds a load phase (N cycles minimum, more with
//  producer gaps) and a shift phase (2N cycles, same per-element
//  cost as the existing S_SUM loop) ahead of the unchanged
//  Pass1/Sum/Pass2/Pass3 pipeline; results then stream out over
//  the last N cycles instead of landing all at once.
// ============================================================
`timescale 1ns/1ps

module eml_softmax_q88_serial #(
    parameter W     = 16,
    parameter F     = 8,
    parameter MAX_N = 8
)(
    input  wire                   clk, rst, start,
    input  wire [3:0]             n_in,
    input  wire signed [W-1:0]    z_in,
    input  wire                   z_valid,
    output reg  signed [W-1:0]    result,
    output reg                    result_valid,
    output reg                    valid,
    output reg                    ovf,
    output reg                    n_err,

    output wire signed [W-1:0] eml_x_out,
    output wire        [W-1:0] eml_y_out,
    input  wire signed [W-1:0] eml_out_in,
    input  wire                 eml_ovf_in
);
    localparam signed [W-1:0] Q88_ONE      = (1 <<< F);
    localparam signed [W-1:0] Q88_ZERO     = {W{1'b0}};
    localparam signed [W-1:0] NEG_SENTINEL = -(1 <<< (W-1));  // most negative representable value, any W

    reg  signed [W-1:0] eml_x;
    reg         [W-1:0] eml_y;
    assign eml_x_out = eml_x;
    assign eml_y_out = eml_y;
    wire signed [W-1:0] eml_out = eml_out_in;
    wire                eml_ovf = eml_ovf_in;

    // shared ALU -- used for S_SHIFT (max-trick), S_SUM, S_LNS_SUB, S_TGT
    reg  signed [W-1:0] alu_a, alu_b;
    reg                 alu_sel;
    wire signed [W:0]   alu_wide = alu_sel
        ? ($signed({alu_a[W-1],alu_a}) - $signed({alu_b[W-1],alu_b}))
        : ($signed({alu_a[W-1],alu_a}) + $signed({alu_b[W-1],alu_b}));
    wire signed [W-1:0] alu_out =
        (alu_wide[W]!=alu_wide[W-1])
        ? (alu_wide[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : alu_wide[W-1:0];

    reg signed [W-1:0] z_buf   [0:MAX_N-1];
    reg signed [W-1:0] exp_buf [0:MAX_N-1];
    reg signed [W-1:0] ln_s_reg, sum_acc;
    reg signed [W-1:0] max_z_reg;
    reg                 err_acc;
    reg [3:0]           n_reg;
    reg [$clog2(MAX_N)-1:0] idx;
    integer k;

    localparam S_IDLE=4'd0,  S_LOAD=4'd1,     S_SHIFT=4'd2,    S_SHIFT_LAT=4'd3,
               S_EXP=4'd4,   S_EXP_LAT=4'd5,  S_SUM=4'd6,      S_SUM_LAT=4'd7,
               S_LNS=4'd8,   S_LNS_LAT=4'd9,  S_LNS_SUB=4'd10, S_TGT=4'd11,
               S_TGT_LAT=4'd12, S_FIN=4'd13,  S_FIN_LAT=4'd14;
    reg [3:0] state;

    always @(posedge clk) begin
        if (rst) begin
            state<=S_IDLE; valid<=0; ovf<=0; n_err<=0; result<=0; result_valid<=0;
            idx<=0; err_acc<=0; n_reg<=0; max_z_reg<=NEG_SENTINEL;
            sum_acc<=Q88_ZERO; ln_s_reg<=Q88_ZERO;
            eml_x<=Q88_ZERO; eml_y<=Q88_ONE[W-1:0];
            alu_a<=0; alu_b<=0; alu_sel<=0;
            for(k=0;k<MAX_N;k=k+1) begin z_buf[k]<=0; exp_buf[k]<=0; end
        end else begin
            valid<=0;
            result_valid<=0;
            case (state)
                S_IDLE: begin
                    err_acc<=0;
                    if (start) begin
                        if (n_in < 4'd2 || n_in > MAX_N) begin
                            n_err<=1; ovf<=1; valid<=1; state<=S_IDLE;
                        end else begin
                            n_err<=0;
                            n_reg<=n_in;
                            idx<=0;
                            max_z_reg<=NEG_SENTINEL;
                            state<=S_LOAD;
                        end
                    end
                end

                // ---- serial load: one logit per cycle, z_valid-gated ----
                S_LOAD: begin
                    if (z_valid) begin
                        z_buf[idx] <= z_in;
                        if (z_in > max_z_reg) max_z_reg <= z_in;
                        if (idx == n_reg-1) begin
                            idx <= 0;
                            state <= S_SHIFT;
                        end else begin
                            idx <= idx + 1;
                        end
                    end
                    // else: hold, wait for the producer -- gaps are fine
                end

                // ---- serial max-trick shift: reuses the shared ALU,
                //      one element per 2 cycles, same pattern as S_SUM ----
                S_SHIFT: begin
                    alu_a <= z_buf[idx]; alu_b <= max_z_reg; alu_sel <= 1;
                    state <= S_SHIFT_LAT;
                end

                S_SHIFT_LAT: begin
                    z_buf[idx] <= alu_out;   // overwrite raw with shifted value
                    err_acc <= err_acc | (alu_wide[W]!=alu_wide[W-1]);
                    if (idx == n_reg-1) begin
                        idx <= 0;
                        eml_x <= z_buf[0];   // z_buf[0] was shifted first, safe to read now
                        eml_y <= Q88_ONE[W-1:0];
                        state <= S_EXP;
                    end else begin
                        idx <= idx + 1;
                        state <= S_SHIFT;
                    end
                end

                // ---- unchanged compute pipeline ----
                S_EXP: state<=S_EXP_LAT;

                S_EXP_LAT: begin
                    exp_buf[idx]<=eml_out; err_acc<=err_acc|eml_ovf;
                    if (idx==n_reg-1) begin
                        sum_acc<=exp_buf[0]; idx<=1; state<=S_SUM;
                    end else begin
                        idx<=idx+1; eml_x<=z_buf[idx+1];
                        eml_y<=Q88_ONE[W-1:0]; state<=S_EXP;
                    end
                end

                S_SUM: begin
                    alu_a<=sum_acc; alu_b<=exp_buf[idx]; alu_sel<=0;
                    state<=S_SUM_LAT;
                end

                S_SUM_LAT: begin
                    sum_acc<=alu_out;
                    err_acc<=err_acc|(alu_wide[W]!=alu_wide[W-1]);
                    if (idx==n_reg-1) begin
                        eml_x<=Q88_ZERO; eml_y<=alu_out[W-1:0]; state<=S_LNS;
                    end else begin
                        idx<=idx+1; state<=S_SUM;
                    end
                end

                S_LNS: state<=S_LNS_LAT;

                S_LNS_LAT: begin
                    err_acc<=err_acc|eml_ovf;
                    alu_a<=Q88_ONE; alu_b<=eml_out; alu_sel<=1;
                    state<=S_LNS_SUB;
                end

                S_LNS_SUB: begin
                    ln_s_reg<=alu_out;
                    err_acc<=err_acc|(alu_wide[W]!=alu_wide[W-1]);
                    idx<=0;
                    alu_a<=z_buf[0]; alu_b<=alu_out; alu_sel<=1;
                    state<=S_TGT;
                end

                S_TGT: state<=S_TGT_LAT;

                S_TGT_LAT: begin
                    err_acc<=err_acc|(alu_wide[W]!=alu_wide[W-1]);
                    eml_x<=alu_out; eml_y<=Q88_ONE[W-1:0]; state<=S_FIN;
                end

                S_FIN: state<=S_FIN_LAT;

                // ---- stream each finished element out directly,
                //      instead of packing into a bus ----
                S_FIN_LAT: begin
                    result <= eml_out;
                    result_valid <= 1;
                    err_acc <= err_acc | eml_ovf;
                    if (idx==n_reg-1) begin
                        ovf   <= err_acc | eml_ovf;
                        valid <= 1;            // final completion, same cycle as last result_valid
                        state <= S_IDLE;
                    end else begin
                        idx<=idx+1;
                        alu_a<=z_buf[idx+1]; alu_b<=ln_s_reg; alu_sel<=1;
                        state<=S_TGT;
                    end
                end

                default: state<=S_IDLE;
            endcase
        end
    end
endmodule
