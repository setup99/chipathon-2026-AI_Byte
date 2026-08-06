`timescale 1ns / 1ps
//============================================================
// AI_BYTE Buffer Bank (Act + Weight + Result)
//
// Three identical single-port SRAMs with one shared size knob:
//   DEPTH  — entries per buffer (default 256)
//   DATA_W — data width (default 8 = INT8)
//   ADDR_W — auto from DEPTH unless overridden
//
// Change buffer size later by editing parameters at the
// instantiation site (top / control block), e.g.:
//
//   ai_byte_buffers #(.DEPTH(512), .DATA_W(8)) u_bufs (...);
//
// Keep Buffer Controller BUFFER_DEPTH / BUFFER_ADDR_W in sync.
//============================================================

module ai_byte_buffers
#(
    parameter integer DEPTH  = 256,
    parameter integer DATA_W = 8,
    parameter integer ADDR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
)
(
    input  wire                     clk,

    // Activation
    input  wire [ADDR_W-1:0]        act_addr,
    input  wire [DATA_W-1:0]        act_wdata,
    output wire [DATA_W-1:0]        act_rdata,
    input  wire                     act_we,
    input  wire                     act_ce,

    // Weight
    input  wire [ADDR_W-1:0]        wt_addr,
    input  wire [DATA_W-1:0]        wt_wdata,
    output wire [DATA_W-1:0]        wt_rdata,
    input  wire                     wt_we,
    input  wire                     wt_ce,

    // Result
    input  wire [ADDR_W-1:0]        res_addr,
    input  wire [DATA_W-1:0]        res_wdata,
    output wire [DATA_W-1:0]        res_rdata,
    input  wire                     res_we,
    input  wire                     res_ce
);

    ai_byte_sram_buffer #(
        .DEPTH  (DEPTH),
        .DATA_W (DATA_W),
        .ADDR_W (ADDR_W)
    ) u_act (
        .clk   (clk),
        .ce    (act_ce),
        .we    (act_we),
        .addr  (act_addr),
        .wdata (act_wdata),
        .rdata (act_rdata)
    );

    ai_byte_sram_buffer #(
        .DEPTH  (DEPTH),
        .DATA_W (DATA_W),
        .ADDR_W (ADDR_W)
    ) u_weight (
        .clk   (clk),
        .ce    (wt_ce),
        .we    (wt_we),
        .addr  (wt_addr),
        .wdata (wt_wdata),
        .rdata (wt_rdata)
    );

    ai_byte_sram_buffer #(
        .DEPTH  (DEPTH),
        .DATA_W (DATA_W),
        .ADDR_W (ADDR_W)
    ) u_result (
        .clk   (clk),
        .ce    (res_ce),
        .we    (res_we),
        .addr  (res_addr),
        .wdata (res_wdata),
        .rdata (res_rdata)
    );

endmodule
