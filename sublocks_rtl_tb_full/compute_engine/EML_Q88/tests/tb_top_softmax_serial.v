`timescale 1ns/1ps

module tb_top_softmax_serial #(
    parameter W = 16,
    parameter F = 8,
    parameter MAX_N = 8
)(
    input  wire                clk, rst, start,
    input  wire [3:0]          n_in,
    input  wire signed [W-1:0] z_in,
    input  wire                z_valid,
    output wire signed [W-1:0] result,
    output wire                result_valid,
    output wire                valid,
    output wire                ovf,
    output wire                n_err
);

    wire signed [W-1:0] eml_x;
    wire        [W-1:0] eml_y;
    wire signed [W-1:0] eml_out;
    wire                 eml_ovf;

    eml_softmax_q88_serial #(.W(W), .F(F), .MAX_N(MAX_N)) dut (
        .clk(clk), .rst(rst), .start(start),
        .n_in(n_in), .z_in(z_in), .z_valid(z_valid),
        .result(result), .result_valid(result_valid),
        .valid(valid), .ovf(ovf), .n_err(n_err),
        .eml_x_out(eml_x), .eml_y_out(eml_y),
        .eml_out_in(eml_out), .eml_ovf_in(eml_ovf)
    );

    eml_tile_q88 #(.W(W), .F(F)) u_tile (
        .x(eml_x), .y(eml_y), .out(eml_out), .ovf(eml_ovf)
    );

endmodule
