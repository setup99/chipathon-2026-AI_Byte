`timescale 1ns / 1ps
//============================================================
// AI_BYTE Single-Port Sync SRAM Buffer (synthesizable RTL)
//
// Register-array model of one Activation / Weight / Result
// buffer. Intended for ASIC synthesis as flip-flops (no
// foundry SRAM macro).
//
// Timing (matches Buffer Controller assumptions)
// ----------------------------------------------
//   • Single-port: one access per cycle
//   • Sync write:  mem[addr] <= wdata when ce & we
//   • Sync read:   rdata     <= mem[addr] when ce & !we
//   • ce=0:        no write; rdata holds last value
//
// Soft-reset / rst_n do NOT clear memory (architecture rule).
// Contents are undefined until the host writes them via MMIF.
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
    // Storage — synthesizable register file (no initial)
    //--------------------------------------------------------

    reg [DATA_W-1:0] mem [0:DEPTH-1];

    //--------------------------------------------------------
    // Sync access
    //--------------------------------------------------------

    always @(posedge clk) begin
        if (ce) begin
            if (we) begin
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
