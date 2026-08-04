`timescale 1ns / 1ps
//============================================================
// AI_BYTE Memory-Mapped Interface (MMIF)
//
// Chip pins → Register File / Buffer Controller decode.
// Does NOT instantiate RF, BC, CU, or SRAMs (those live in
// control_block / top).
//
// Pin contract (signal I/O)
// -------------------------
//   clk, rst_n
//   addr[3:0], data[7:0] (inout), we, re
//   irq
//
// Decode
// ------
//   addr != 0x6  →  RF  (reg_*)
//   addr == 0x6  →  BUFFER_DATA → BC (cpu_*)
//                   using RF broadcast BUFFER_SELECT / BUFFER_ADDR
//
// Single-cycle: no READY/WAIT. data driven only while re=1
// (and we=0); otherwise Hi-Z.
//============================================================

module ai_byte_mmif
#(
    parameter DATA_W        = 8,
    parameter REG_ADDR_W    = 4,
    parameter BUFFER_ADDR_W = 8
)
(
    //--------------------------------------------------------
    // Chip pins
    //--------------------------------------------------------
    input  wire                         clk,      // unused (combinational decode)
    input  wire                         rst_n,    // unused (combinational decode)
    input  wire [REG_ADDR_W-1:0]        addr,
    inout  wire [DATA_W-1:0]            data,
    input  wire                         we,
    input  wire                         re,
    output wire                         irq,

    //--------------------------------------------------------
    // Interrupt from control block
    //--------------------------------------------------------
    input  wire                         irq_i,

    //--------------------------------------------------------
    // Register File port
    //--------------------------------------------------------
    output wire [REG_ADDR_W-1:0]        reg_addr,
    output wire                         reg_we,
    output wire                         reg_re,
    output wire [DATA_W-1:0]            reg_wdata,
    input  wire [DATA_W-1:0]            reg_rdata,

    //--------------------------------------------------------
    // RF broadcast (BUFFER_DATA routing context)
    //--------------------------------------------------------
    input  wire [DATA_W-1:0]            buffer_select_i,
    input  wire [BUFFER_ADDR_W-1:0]     buffer_addr_i,

    //--------------------------------------------------------
    // Buffer Controller CPU port
    //--------------------------------------------------------
    output wire [1:0]                   cpu_buf_sel,
    output wire [BUFFER_ADDR_W-1:0]     cpu_buf_addr,
    output wire [DATA_W-1:0]            cpu_wdata,
    input  wire [DATA_W-1:0]            cpu_rdata,
    output wire                         cpu_we,
    output wire                         cpu_re
);

    localparam [REG_ADDR_W-1:0] ADDR_BUFFER_DATA = 4'h6;

    wire is_buf = (addr == ADDR_BUFFER_DATA);

    //--------------------------------------------------------
    // IRQ pass-through
    //--------------------------------------------------------
    assign irq = irq_i;

    //--------------------------------------------------------
    // RF path (all addresses except BUFFER_DATA)
    //--------------------------------------------------------
    assign reg_addr  = addr;
    assign reg_we    = we & ~is_buf;
    assign reg_re    = re & ~is_buf;
    assign reg_wdata = data;

    //--------------------------------------------------------
    // BC BUFFER_DATA path
    //--------------------------------------------------------
    assign cpu_buf_sel  = buffer_select_i[1:0];
    assign cpu_buf_addr = buffer_addr_i;
    assign cpu_wdata    = data;
    assign cpu_we       = we & is_buf;
    assign cpu_re       = re & is_buf;

    //--------------------------------------------------------
    // Bidirectional data bus
    // Drive only on read (re=1, we=0). Write cycles: Hi-Z so
    // the host can drive data.
    //--------------------------------------------------------
    wire [DATA_W-1:0] read_data = is_buf ? cpu_rdata : reg_rdata;
    wire              drive_data = re & ~we;

    assign data = drive_data ? read_data : {DATA_W{1'bz}};

endmodule
