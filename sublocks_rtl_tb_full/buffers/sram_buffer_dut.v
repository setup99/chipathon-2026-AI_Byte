`timescale 1ns / 1ps
// Cocotb DUT wrapper — small DEPTH for fast unit tests.
// Production size is set at top-level (default 256 in RTL).

module sram_buffer_dut
#(
    parameter integer DEPTH  = 16,
    parameter integer DATA_W = 8,
    parameter integer ADDR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
)
(
    input  wire                     clk,
    input  wire                     ce,
    input  wire                     we,
    input  wire [ADDR_W-1:0]        addr,
    input  wire [DATA_W-1:0]        wdata,
    output wire [DATA_W-1:0]        rdata
);

    ai_byte_sram_buffer #(
        .DEPTH  (DEPTH),
        .DATA_W (DATA_W),
        .ADDR_W (ADDR_W)
    ) u_sram (
        .clk   (clk),
        .ce    (ce),
        .we    (we),
        .addr  (addr),
        .wdata (wdata),
        .rdata (rdata)
    );

endmodule
