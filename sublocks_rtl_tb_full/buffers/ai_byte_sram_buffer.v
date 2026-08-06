`timescale 1ns / 1ps
//============================================================
// AI_BYTE Single-Port Sync SRAM Buffer
//
// Behavioral model of one Activation / Weight / Result buffer.
// Depth and width are parameters so sizes can change later
// without rewriting the module (or the Buffer Controller
// ADDR_W / DEPTH parameters — keep them matched at top-level).
//
// Timing (matches Buffer Controller assumptions)
// ----------------------------------------------
//   • Single-port: one access per cycle
//   • Sync write:  mem[addr] <= wdata when ce & we
//   • Sync read:   rdata     <= mem[addr] when ce & !we
//   • ce=0:        no write; rdata holds last value
//
// Soft-reset does NOT clear contents (architecture rule).
// No rst_n on the array itself.
//
// For GF180 tapeout, replace this body with a foundry SRAM
// macro wrapper that preserves the same ports / timing.
//============================================================

module ai_byte_sram_buffer
#(
    parameter integer DEPTH  = 256,
    parameter integer DATA_W = 8,
    // Auto-sized address bus; override only if you need a wider bus
    parameter integer ADDR_W = (DEPTH <= 1) ? 1 : $clog2(DEPTH)
)
(
    input  wire                     clk,

    input  wire                     ce,      // chip enable
    input  wire                     we,      // write enable (ignored if !ce)
    input  wire [ADDR_W-1:0]        addr,
    input  wire [DATA_W-1:0]        wdata,
    output reg  [DATA_W-1:0]        rdata
);

    //--------------------------------------------------------
    // Storage
    //--------------------------------------------------------

    (* ram_style = "block" *)  // hint for FPGA flows; ignored by many ASIC tools
    reg [DATA_W-1:0] mem [0:DEPTH-1];

    integer i;
    initial begin
        for (i = 0; i < DEPTH; i = i + 1)
            mem[i] = {DATA_W{1'b0}};
        rdata = {DATA_W{1'b0}};
    end

    //--------------------------------------------------------
    // Sync access
    //--------------------------------------------------------

    always @(posedge clk) begin
        if (ce) begin
            if (we) begin
                // Guard out-of-range in sim if ADDR_W > clog2(DEPTH)
                if (addr < DEPTH)
                    mem[addr] <= wdata;
            end
            else begin
                if (addr < DEPTH)
                    rdata <= mem[addr];
            end
        end
        // ce=0: hold rdata, no write
    end

endmodule
