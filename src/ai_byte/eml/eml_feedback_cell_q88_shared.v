// ============================================================
//  eml_feedback_cell_q88_shared.v
//  Lightweight dual-mux feedback cell for Q8.8 EML tile
//
//  SHARED-TILE VARIANT -- see eml_sigmoid_q88_shared.v for the
//  rationale. Identical logic to eml_feedback_cell_q88.v; only
//  the tile's physical location changed (external request/
//  response instead of a private u_tile instance). Since this
//  block only ever needs the tile for exactly one cycle per
//  valid_in pulse (no multi-state FSM), x_in/y_in are still pure
//  combinational wires -- just routed out to the shared tile
//  instead of into a private one.
//
//  Mode table (sel_x, sel_y):
//    0,0  feed-forward    out = eml(x_ext, y_ext)
//    1,0  iterate X       out = eml(out_prev, y_ext)
//    0,1  iterate Y       out = eml(x_ext, out_prev)
//    1,1  cross-feedback  out = eml(out_prev, out_prev)
//
//  fb_reg resets to Q88_ONE = 0x0100 (1.0) on rst_n (active-low).
// ============================================================
`timescale 1ns/1ps

module eml_feedback_cell_q88_shared #(
    parameter W = 16,
    parameter F = 8
)(
    input  wire             clk,
    input  wire             rst_n,
    input  wire             valid_in,
    input  wire signed [W-1:0] x_ext,
    input  wire        [W-1:0] y_ext,
    input  wire                sel_x,
    input  wire                sel_y,
    output reg  signed [W-1:0] out,
    output reg                 ovf,
    output reg                 valid_out,

    output wire signed [W-1:0] eml_x_out,
    output wire        [W-1:0] eml_y_out,
    input  wire signed [W-1:0] eml_out_in,
    input  wire                 eml_ovf_in
);
    localparam signed [W-1:0] Q88_ONE = 16'sh0100;  // 1.0

    reg [W-1:0] fb_reg;

    wire signed [W-1:0] x_in = sel_x ? $signed(fb_reg) : x_ext;
    wire        [W-1:0] y_in = sel_y ? fb_reg : y_ext;

    assign eml_x_out = x_in;
    assign eml_y_out = y_in;
    wire signed [W-1:0] tile_out = eml_out_in;
    wire                tile_ovf = eml_ovf_in;

    always @(posedge clk) begin
        if (!rst_n) begin
            out <= 0; ovf <= 0; valid_out <= 0;
            fb_reg <= Q88_ONE;
        end else begin
            valid_out <= valid_in;
            if (valid_in) begin
                out    <= tile_out;
                ovf    <= tile_ovf;
                fb_reg <= tile_out;
            end
        end
    end
endmodule
