`timescale 1ns / 1ps
//============================================================================
// AI_BYTE Core SoC — control_wrap + buffers + compute engines
// (lives in src/ai_byte/top/ — not under control/)
// Default tapeout: Act64 / Wt16 / Res16 / TILE=4
// Chip boundary: ai_byte_top = MMIF + this module.
//============================================================================

module ai_byte_core
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
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire [REG_ADDR_W-1:0]        reg_addr,
    input  wire                         reg_we,
    input  wire                         reg_re,
    input  wire [DATA_W-1:0]            reg_wdata,
    output wire [DATA_W-1:0]            reg_rdata,

    input  wire [1:0]                   cpu_buf_sel,
    input  wire [BUFFER_ADDR_W-1:0]     cpu_buf_addr,
    input  wire [DATA_W-1:0]            cpu_wdata,
    output wire [DATA_W-1:0]            cpu_rdata,
    input  wire                         cpu_we,
    input  wire                         cpu_re,

    output wire                         irq,
    output wire [DATA_W-1:0]            buffer_select_o,
    output wire [BUFFER_ADDR_W-1:0]     buffer_addr_o,
    output wire [2:0]                   debug_state
);

    // Combined async-chip + soft reset for CEs (both active-low)
    wire soft_reset_n;
    wire ce_rst_n = rst_n & soft_reset_n;

    wire sram_act_ce, sram_act_we, sram_wt_ce, sram_wt_we, sram_res_ce, sram_res_we;
    wire [ACT_ADDR_W-1:0] sram_act_addr;
    wire [WT_ADDR_W-1:0]  sram_wt_addr;
    wire [RES_ADDR_W-1:0] sram_res_addr;
    wire [DATA_W-1:0] sram_act_wdata, sram_wt_wdata, sram_res_wdata;
    wire [DATA_W-1:0] sram_act_rdata, sram_wt_rdata, sram_res_rdata;

    wire wrap_bias_en, wrap_relu_en, wrap_pool_en, wrap_pool_op, wrap_scale_en;
    wire [1:0] wrap_alu_opcode;
    wire signed [15:0] wrap_in_data;
    wire wrap_in_valid, wrap_in_ready;
    wire signed [15:0] wrap_out_data16;
    wire signed [7:0] wrap_out_data8;
    wire wrap_out_is_int8, wrap_out_valid, wrap_out_ready, wrap_busy, wrap_ovf;

    wire eml_start, eml_z_valid, eml_sel_x, eml_sel_y;
    wire [2:0] eml_opcode_w;
    wire signed [15:0] eml_x_in, eml_z_in, eml_x_ext, eml_result;
    wire [15:0] eml_y_ext;
    wire [3:0] eml_n_in;
    wire eml_valid, eml_ovf, eml_n_err, eml_busy, eml_ready;

    wire sa_start, sa_busy, sa_done, sa_w_load, sa_y_row_valid;
    wire [3:0] sa_op_sel;
    wire [1:0] sa_w_row, sa_w_col, sa_y_row_idx;
    wire signed [7:0] sa_w_data;
    wire [TILE*8-1:0] sa_x_in;
    wire [TILE*16-1:0] sa_y_row_data;

    ai_byte_control_wrap #(
        .DATA_W(DATA_W), .REG_ADDR_W(REG_ADDR_W),
        .ACT_DEPTH(ACT_DEPTH), .WT_DEPTH(WT_DEPTH), .RES_DEPTH(RES_DEPTH),
        .TILE(TILE), .CNN_ACT_N(CNN_ACT_N), .SOFTMAX_MAX_N(SOFTMAX_MAX_N),
        .ENABLE_SA(ENABLE_SA), .ENABLE_MICROPROG(ENABLE_MICROPROG),
        .ENABLE_SOFTMAX(ENABLE_SOFTMAX)
    ) u_ctrl (
        .clk(clk), .rst_n(rst_n),
        .reg_addr(reg_addr), .reg_we(reg_we), .reg_re(reg_re),
        .reg_wdata(reg_wdata), .reg_rdata(reg_rdata),
        .cpu_buf_sel(cpu_buf_sel), .cpu_buf_addr(cpu_buf_addr),
        .cpu_wdata(cpu_wdata), .cpu_rdata(cpu_rdata),
        .cpu_we(cpu_we), .cpu_re(cpu_re),
        .irq(irq), .buffer_select_o(buffer_select_o), .buffer_addr_o(buffer_addr_o),
        .debug_state(debug_state),
        .soft_reset_n(soft_reset_n),
        .sram_act_ce(sram_act_ce), .sram_act_we(sram_act_we),
        .sram_act_addr(sram_act_addr), .sram_act_wdata(sram_act_wdata),
        .sram_act_rdata(sram_act_rdata),
        .sram_wt_ce(sram_wt_ce), .sram_wt_we(sram_wt_we),
        .sram_wt_addr(sram_wt_addr), .sram_wt_wdata(sram_wt_wdata),
        .sram_wt_rdata(sram_wt_rdata),
        .sram_res_ce(sram_res_ce), .sram_res_we(sram_res_we),
        .sram_res_addr(sram_res_addr), .sram_res_wdata(sram_res_wdata),
        .sram_res_rdata(sram_res_rdata),
        .wrap_bias_en(wrap_bias_en), .wrap_relu_en(wrap_relu_en),
        .wrap_pool_en(wrap_pool_en), .wrap_alu_opcode(wrap_alu_opcode),
        .wrap_pool_op(wrap_pool_op), .wrap_scale_en(wrap_scale_en),
        .wrap_in_data(wrap_in_data), .wrap_in_valid(wrap_in_valid),
        .wrap_in_ready(wrap_in_ready),
        .wrap_out_data16(wrap_out_data16), .wrap_out_data8(wrap_out_data8),
        .wrap_out_is_int8(wrap_out_is_int8), .wrap_out_valid(wrap_out_valid),
        .wrap_out_ready(wrap_out_ready), .wrap_busy(wrap_busy),
        .eml_start(eml_start), .eml_opcode_o(eml_opcode_w),
        .eml_x_in(eml_x_in), .eml_n_in(eml_n_in),
        .eml_z_in(eml_z_in), .eml_z_valid(eml_z_valid),
        .eml_x_ext(eml_x_ext), .eml_y_ext(eml_y_ext),
        .eml_sel_x(eml_sel_x), .eml_sel_y(eml_sel_y),
        .eml_result(eml_result), .eml_valid(eml_valid), .eml_ovf(eml_ovf),
        .eml_n_err(eml_n_err), .eml_busy(eml_busy), .eml_ready(eml_ready),
        .sa_start(sa_start), .sa_op_sel(sa_op_sel), .sa_busy(sa_busy), .sa_done(sa_done),
        .sa_w_load(sa_w_load), .sa_w_row(sa_w_row), .sa_w_col(sa_w_col),
        .sa_w_data(sa_w_data), .sa_x_in(sa_x_in),
        .sa_y_row_idx(sa_y_row_idx), .sa_y_row_data(sa_y_row_data),
        .sa_y_row_valid(sa_y_row_valid)
    );

    ai_byte_sram_buffer #(.DEPTH(ACT_DEPTH), .DATA_W(DATA_W), .ADDR_W(ACT_ADDR_W)) u_act (
        .clk(clk), .ce(sram_act_ce), .we(sram_act_we),
        .addr(sram_act_addr), .wdata(sram_act_wdata), .rdata(sram_act_rdata)
    );
    ai_byte_sram_buffer #(.DEPTH(WT_DEPTH), .DATA_W(DATA_W), .ADDR_W(WT_ADDR_W)) u_wt (
        .clk(clk), .ce(sram_wt_ce), .we(sram_wt_we),
        .addr(sram_wt_addr), .wdata(sram_wt_wdata), .rdata(sram_wt_rdata)
    );
    ai_byte_sram_buffer #(.DEPTH(RES_DEPTH), .DATA_W(DATA_W), .ADDR_W(RES_ADDR_W)) u_res (
        .clk(clk), .ce(sram_res_ce), .we(sram_res_we),
        .addr(sram_res_addr), .wdata(sram_res_wdata), .rdata(sram_res_rdata)
    );

    block_wrapper u_wrap (
        .clk(clk), .rst_n(ce_rst_n),
        .bias_en(wrap_bias_en), .relu_en(wrap_relu_en), .pool_en(wrap_pool_en),
        .alu_opcode(wrap_alu_opcode), .pool_op(wrap_pool_op), .scale_en(wrap_scale_en),
        .in_data(wrap_in_data), .in_valid(wrap_in_valid), .in_ready(wrap_in_ready),
        .out_data16(wrap_out_data16), .out_data8(wrap_out_data8),
        .out_is_int8(wrap_out_is_int8), .out_valid(wrap_out_valid),
        .out_ready(wrap_out_ready), .out_overflow(wrap_ovf), .busy(wrap_busy)
    );

    eml_wrapper_q88_serial u_eml (
        .clk(clk), .rst_n(ce_rst_n), .start(eml_start), .opcode(eml_opcode_w),
        .x_in(eml_x_in), .n_in(eml_n_in), .z_in(eml_z_in), .z_valid(eml_z_valid),
        .x_ext(eml_x_ext), .y_ext(eml_y_ext), .sel_x(eml_sel_x), .sel_y(eml_sel_y),
        .result(eml_result), .valid(eml_valid), .ovf(eml_ovf), .n_err(eml_n_err),
        .busy(eml_busy), .ready(eml_ready)
    );

    generate
        if (ENABLE_SA) begin : g_sa
            gemm_systolic_2d #(.M(TILE), .P(TILE), .N(TILE)) u_sa (
                .clk(clk), .rst_n(ce_rst_n),
                .op_sel(sa_op_sel), .start(sa_start), .busy(sa_busy), .done(sa_done),
                .w_load(sa_w_load), .w_load_row(sa_w_row), .w_load_col(sa_w_col),
                .w_load_data(sa_w_data),
                .x_in_data(sa_x_in),
                .y_row_idx(sa_y_row_idx), .y_row_data(sa_y_row_data),
                .y_row_valid(sa_y_row_valid)
            );
        end else begin : g_nosa
            assign sa_busy = 1'b0;
            assign sa_done = 1'b0;
            assign sa_y_row_idx = 2'b0;
            assign sa_y_row_data = {TILE*16{1'b0}};
            assign sa_y_row_valid = 1'b0;
        end
    endgenerate

endmodule
