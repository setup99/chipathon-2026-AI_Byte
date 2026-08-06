// ============================================================
//  eml_recip_q88_shared.v
//  1/x  in Q8.8 -- FSM, two EML passes
//
//  SHARED-TILE VARIANT -- see eml_sigmoid_q88_shared.v for the
//  rationale. Identical FSM/logic to eml_recip_q88.v; only the
//  tile's physical location changed.
// ============================================================
`timescale 1ns/1ps

module eml_recip_q88_shared #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire             clk, rst_n, start,
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

    reg  signed [W-1:0] alu_a, alu_b;
    wire signed [W:0]   alu_wide = $signed({alu_a[W-1],alu_a})
                                  - $signed({alu_b[W-1],alu_b});
    wire signed [W-1:0] alu_out  =
        (alu_wide[W] != alu_wide[W-1])
        ? (alu_wide[W] ? {1'b1,{(W-1){1'b0}}} : {1'b0,{(W-1){1'b1}}})
        : alu_wide[W-1:0];

    reg err_acc;

    localparam S_IDLE=2'd0, S_P1=2'd1, S_SUB=2'd2, S_P2=2'd3;
    reg [1:0] state;

    always @(posedge clk) begin
        if (!rst_n) begin
            state<=S_IDLE; result<=0; valid<=0; ovf<=0;
            eml_x<=0; eml_y<=Q88_ONE[W-1:0];
            alu_a<=0; alu_b<=0; err_acc<=0;
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
                // eml_out = 1 - ln(x)
                S_P1: begin
                    err_acc <= eml_ovf;
                    alu_a <= eml_out;
                    alu_b <= Q88_ONE;
                    state <= S_SUB;
                end
                // alu_out = (1-ln x) - 1 = -ln(x)
                S_SUB: begin
                    err_acc <= err_acc | (alu_wide[W]!=alu_wide[W-1]);
                    eml_x <= alu_out;
                    eml_y <= Q88_ONE[W-1:0];
                    state <= S_P2;
                end
                // eml_out = exp(-ln x) = 1/x
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
