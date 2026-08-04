`timescale 1ns / 1ps
// Cocotb DUT wrapper for the 3-buffer bank (small DEPTH).

module buffers_dut
#(
    parameter integer DEPTH  = 16,
    parameter integer DATA_W = 8,
    parameter integer ADDR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
)
(
    input  wire                     clk,

    input  wire [ADDR_W-1:0]        act_addr,
    input  wire [DATA_W-1:0]        act_wdata,
    output wire [DATA_W-1:0]        act_rdata,
    input  wire                     act_we,
    input  wire                     act_ce,

    input  wire [ADDR_W-1:0]        wt_addr,
    input  wire [DATA_W-1:0]        wt_wdata,
    output wire [DATA_W-1:0]        wt_rdata,
    input  wire                     wt_we,
    input  wire                     wt_ce,

    input  wire [ADDR_W-1:0]        res_addr,
    input  wire [DATA_W-1:0]        res_wdata,
    output wire [DATA_W-1:0]        res_rdata,
    input  wire                     res_we,
    input  wire                     res_ce
);

    ai_byte_buffers #(
        .DEPTH  (DEPTH),
        .DATA_W (DATA_W),
        .ADDR_W (ADDR_W)
    ) u_bufs (
        .clk       (clk),
        .act_addr  (act_addr),
        .act_wdata (act_wdata),
        .act_rdata (act_rdata),
        .act_we    (act_we),
        .act_ce    (act_ce),
        .wt_addr   (wt_addr),
        .wt_wdata  (wt_wdata),
        .wt_rdata  (wt_rdata),
        .wt_we     (wt_we),
        .wt_ce     (wt_ce),
        .res_addr  (res_addr),
        .res_wdata (res_wdata),
        .res_rdata (res_rdata),
        .res_we    (res_we),
        .res_ce    (res_ce)
    );

endmodule
