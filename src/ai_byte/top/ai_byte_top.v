`timescale 1ns / 1ps
//============================================================================
// AI_BYTE Chip Top — MMIF + ai_byte_core  (lives in src/ai_byte/top/)
// Block A pin contract (signal I/O): clk, rst_n, addr[3:0], data[7:0],
// we, re, irq  (= 17 signals within 22-pin budget).
//============================================================================

module ai_byte_top
#(
    parameter DATA_W           = 8,
    parameter REG_ADDR_W       = 4,
    parameter ACT_DEPTH        = 64,
    parameter WT_DEPTH         = 16,
    parameter RES_DEPTH        = 16,
    parameter TILE             = 4,
    parameter CNN_ACT_N        = TILE*TILE,
    parameter SOFTMAX_MAX_N    = 8,
    parameter ENABLE_SA        = 1,
    parameter ENABLE_MICROPROG = 1,
    parameter ENABLE_SOFTMAX   = 1,
    parameter ACT_ADDR_W       = (ACT_DEPTH<=1)?1:$clog2(ACT_DEPTH),
    parameter WT_ADDR_W        = (WT_DEPTH<=1)?1:$clog2(WT_DEPTH),
    parameter RES_ADDR_W       = (RES_DEPTH<=1)?1:$clog2(RES_DEPTH),
    parameter BUFFER_ADDR_W    = (ACT_ADDR_W>WT_ADDR_W)?
                                 ((ACT_ADDR_W>RES_ADDR_W)?ACT_ADDR_W:RES_ADDR_W):
                                 ((WT_ADDR_W>RES_ADDR_W)?WT_ADDR_W:RES_ADDR_W)
)
(
`ifdef USE_POWER_PINS
    inout  wire                         VDD,
    inout  wire                         VSS,
`endif
    input  wire                         clk,
    input  wire                         rst_n,

    // Chip / Block A host pins
    input  wire [REG_ADDR_W-1:0]        addr,
    inout  wire [DATA_W-1:0]            data,
    input  wire                         we,
    input  wire                         re,
    output wire                         irq,

    // Optional observability (not required on package pins)
    output wire [2:0]                   debug_state
);

    // A02 padframe abutment: Metal2 power pins at W12/W13 (see connectors/).
    // LibreLane places these macros at fixed top-level coords (MACROS).
    // Skip when the D10-style A02_A wrapper owns the connectors (top-level).
`ifdef USE_POWER_PINS
`ifndef AI_BYTE_NO_POWER_CONN
    (* keep *) (* keep_hierarchy *) vss_conn u_vss_conn (.VSS(VSS));
    (* keep *) (* keep_hierarchy *) vdd_conn u_vdd_conn (.VDD(VDD));
`endif
`endif

    wire [REG_ADDR_W-1:0]    reg_addr;
    wire                     reg_we, reg_re;
    wire [DATA_W-1:0]        reg_wdata, reg_rdata;

    wire [1:0]               cpu_buf_sel;
    wire [BUFFER_ADDR_W-1:0] cpu_buf_addr;
    wire [DATA_W-1:0]        cpu_wdata, cpu_rdata;
    wire                     cpu_we, cpu_re;

    wire [DATA_W-1:0]        buffer_select_o;
    wire [BUFFER_ADDR_W-1:0] buffer_addr_o;
    wire                     irq_core;

    ai_byte_mmif #(
        .DATA_W(DATA_W),
        .REG_ADDR_W(REG_ADDR_W),
        .BUFFER_ADDR_W(BUFFER_ADDR_W)
    ) u_mmif (
        .clk(clk),
        .rst_n(rst_n),
        .addr(addr),
        .data(data),
        .we(we),
        .re(re),
        .irq(irq),
        .irq_i(irq_core),
        .reg_addr(reg_addr),
        .reg_we(reg_we),
        .reg_re(reg_re),
        .reg_wdata(reg_wdata),
        .reg_rdata(reg_rdata),
        .buffer_select_i(buffer_select_o),
        .buffer_addr_i(buffer_addr_o),
        .cpu_buf_sel(cpu_buf_sel),
        .cpu_buf_addr(cpu_buf_addr),
        .cpu_wdata(cpu_wdata),
        .cpu_rdata(cpu_rdata),
        .cpu_we(cpu_we),
        .cpu_re(cpu_re)
    );

    ai_byte_core #(
        .DATA_W(DATA_W),
        .REG_ADDR_W(REG_ADDR_W),
        .ACT_DEPTH(ACT_DEPTH),
        .WT_DEPTH(WT_DEPTH),
        .RES_DEPTH(RES_DEPTH),
        .TILE(TILE),
        .CNN_ACT_N(CNN_ACT_N),
        .SOFTMAX_MAX_N(SOFTMAX_MAX_N),
        .ENABLE_SA(ENABLE_SA),
        .ENABLE_MICROPROG(ENABLE_MICROPROG),
        .ENABLE_SOFTMAX(ENABLE_SOFTMAX)
    ) u_core (
        .clk(clk),
        .rst_n(rst_n),
        .reg_addr(reg_addr),
        .reg_we(reg_we),
        .reg_re(reg_re),
        .reg_wdata(reg_wdata),
        .reg_rdata(reg_rdata),
        .cpu_buf_sel(cpu_buf_sel),
        .cpu_buf_addr(cpu_buf_addr),
        .cpu_wdata(cpu_wdata),
        .cpu_rdata(cpu_rdata),
        .cpu_we(cpu_we),
        .cpu_re(cpu_re),
        .irq(irq_core),
        .buffer_select_o(buffer_select_o),
        .buffer_addr_o(buffer_addr_o),
        .debug_state(debug_state)
    );

endmodule
