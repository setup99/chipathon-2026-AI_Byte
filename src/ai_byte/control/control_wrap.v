`timescale 1ns / 1ps
//============================================================================
// AI_BYTE Control Path Wrap — RF + CU + BC only
// Drives SRAM and CE through ports; does not instantiate buffers or engines.
//============================================================================

module ai_byte_control_wrap
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

    // MMIF → RF
    input  wire [REG_ADDR_W-1:0]        reg_addr,
    input  wire                         reg_we,
    input  wire                         reg_re,
    input  wire [DATA_W-1:0]            reg_wdata,
    output wire [DATA_W-1:0]            reg_rdata,

    // MMIF → BC (BUFFER_DATA)
    input  wire [1:0]                   cpu_buf_sel,
    input  wire [BUFFER_ADDR_W-1:0]     cpu_buf_addr,
    input  wire [DATA_W-1:0]            cpu_wdata,
    output wire [DATA_W-1:0]            cpu_rdata,
    input  wire                         cpu_we,
    input  wire                         cpu_re,

    output wire                         irq,
    output wire [DATA_W-1:0]            buffer_select_o,
    output wire [BUFFER_ADDR_W-1:0]     buffer_addr_o,
    output wire [2:0]                   debug_state,
    output wire                         soft_reset_n,   // active-low soft reset (1-cycle assert)

    // SRAM ports
    output wire                         sram_act_ce,
    output wire                         sram_act_we,
    output wire [ACT_ADDR_W-1:0]        sram_act_addr,
    output wire [DATA_W-1:0]            sram_act_wdata,
    input  wire [DATA_W-1:0]            sram_act_rdata,

    output wire                         sram_wt_ce,
    output wire                         sram_wt_we,
    output wire [WT_ADDR_W-1:0]         sram_wt_addr,
    output wire [DATA_W-1:0]            sram_wt_wdata,
    input  wire [DATA_W-1:0]            sram_wt_rdata,

    output wire                         sram_res_ce,
    output wire                         sram_res_we,
    output wire [RES_ADDR_W-1:0]        sram_res_addr,
    output wire [DATA_W-1:0]            sram_res_wdata,
    input  wire [DATA_W-1:0]            sram_res_rdata,

    // Post wrapper
    output wire                         wrap_bias_en,
    output wire                         wrap_relu_en,
    output wire                         wrap_pool_en,
    output wire [1:0]                   wrap_alu_opcode,
    output wire                         wrap_pool_op,
    output wire                         wrap_scale_en,
    output wire signed [15:0]           wrap_in_data,
    output wire                         wrap_in_valid,
    input  wire                         wrap_in_ready,
    input  wire signed [15:0]           wrap_out_data16,
    input  wire signed [7:0]            wrap_out_data8,
    input  wire                         wrap_out_is_int8,
    input  wire                         wrap_out_valid,
    output wire                         wrap_out_ready,
    input  wire                         wrap_busy,

    // EML
    output wire                         eml_start,
    output wire [2:0]                   eml_opcode_o,
    output wire signed [15:0]           eml_x_in,
    output wire [3:0]                   eml_n_in,
    output wire signed [15:0]           eml_z_in,
    output wire                         eml_z_valid,
    output wire signed [15:0]           eml_x_ext,
    output wire [15:0]                  eml_y_ext,
    output wire                         eml_sel_x,
    output wire                         eml_sel_y,
    input  wire signed [15:0]           eml_result,
    input  wire                         eml_valid,
    input  wire                         eml_ovf,
    input  wire                         eml_n_err,
    input  wire                         eml_busy,
    input  wire                         eml_ready,

    // SA
    output wire                         sa_start,
    output wire [3:0]                   sa_op_sel,
    input  wire                         sa_busy,
    input  wire                         sa_done,
    output wire                         sa_w_load,
    output wire [1:0]                   sa_w_row,
    output wire [1:0]                   sa_w_col,
    output wire signed [7:0]            sa_w_data,
    output wire [TILE*8-1:0]            sa_x_in,
    input  wire [1:0]                   sa_y_row_idx,
    input  wire [TILE*16-1:0]           sa_y_row_data,
    input  wire                         sa_y_row_valid
);

    wire start_pulse, soft_reset_n_rf, irq_clear_pulse;
    wire [3:0] opcode_o;
    wire [DATA_W-1:0] config_o, feature_cols_o, softmax_n_o;
    wire [DATA_W-1:0] feature_rows_o, input_channels_o, output_channels_o;
    wire [7:0] status_o;
    wire busy_o;
    wire buffer_addr_inc;

    wire relu_en, pool_en, pool_type, bias_en, scale_en, eml_scale_en;
    wire [2:0] compute_unit;
    wire [1:0] alu_subop;
    wire [2:0] eml_opcode;
    wire [3:0] softmax_n;
    wire [7:0] feature_cols;
    wire bc_start, mode;
    wire bc_busy, bc_done, bc_error;
    wire act_ready, weight_ready, result_ready;

    assign soft_reset_n = soft_reset_n_rf;

    ai_byte_reg_file_v2 #(
        .DATA_W(DATA_W), .REG_ADDR_W(REG_ADDR_W), .BUFFER_ADDR_W(BUFFER_ADDR_W)
    ) u_rf (
        .clk(clk), .rst_n(rst_n),
        .reg_addr(reg_addr), .reg_we(reg_we), .reg_re(reg_re),
        .reg_wdata(reg_wdata), .reg_rdata(reg_rdata),
        .status_i(status_o), .busy_i(busy_o),
        .buffer_addr_inc(buffer_addr_inc),
        .start_pulse(start_pulse), .soft_reset_n(soft_reset_n_rf),
        .irq_clear_pulse(irq_clear_pulse),
        .opcode_o(opcode_o), .config_o(config_o),
        .buffer_select_o(buffer_select_o), .buffer_addr_o(buffer_addr_o),
        .feature_rows_o(feature_rows_o), .feature_cols_o(feature_cols_o),
        .input_channels_o(input_channels_o), .output_channels_o(output_channels_o),
        .softmax_n_o(softmax_n_o)
    );

    ai_byte_control_unit_v2 #(
        .ENABLE_SA(ENABLE_SA),
        .ENABLE_MICROPROG(ENABLE_MICROPROG),
        .ENABLE_SOFTMAX(ENABLE_SOFTMAX),
        .SOFTMAX_MAX_N(SOFTMAX_MAX_N)
    ) u_cu (
        .clk(clk), .rst_n(rst_n),
        .start_pulse(start_pulse), .soft_reset_n(soft_reset_n_rf),
        .irq_clear(irq_clear_pulse),
        .opcode_reg(opcode_o), .config_reg(config_o),
        .softmax_n_reg(softmax_n_o), .feature_cols_reg(feature_cols_o),
        .status_o(status_o), .irq(irq), .busy_o(busy_o),
        .done_o(), .error_o(),
        .relu_en(relu_en), .pool_en(pool_en), .pool_type(pool_type),
        .bias_en(bias_en), .scale_en(scale_en), .eml_scale_en(eml_scale_en),
        .compute_unit(compute_unit), .alu_subop(alu_subop),
        .eml_opcode(eml_opcode), .softmax_n(softmax_n), .feature_cols(feature_cols),
        .bc_start(bc_start), .mode(mode),
        .busy(bc_busy), .done(bc_done), .error(bc_error),
        .act_ready(act_ready), .weight_ready(weight_ready), .result_ready(result_ready),
        .debug_state(debug_state)
    );

    ai_byte_buffer_ctrl_v2 #(
        .DATA_W(DATA_W), .ACT_DEPTH(ACT_DEPTH), .WT_DEPTH(WT_DEPTH),
        .RES_DEPTH(RES_DEPTH), .TILE(TILE), .CNN_ACT_N(CNN_ACT_N),
        .ENABLE_SA(ENABLE_SA), .ENABLE_MICROPROG(ENABLE_MICROPROG),
        .BUF_ADDR_W(BUFFER_ADDR_W)
    ) u_bc (
        .clk(clk), .rst_n(rst_n),
        .bc_start(bc_start), .mode(mode), .soft_reset_n(soft_reset_n_rf),
        .compute_unit(compute_unit), .alu_subop(alu_subop), .eml_opcode(eml_opcode),
        .softmax_n(softmax_n), .feature_cols(feature_cols),
        .relu_en(relu_en), .pool_en(pool_en), .pool_type(pool_type),
        .bias_en(bias_en), .scale_en(scale_en), .eml_scale_en(eml_scale_en),
        .busy(bc_busy), .done(bc_done), .error(bc_error),
        .act_ready(act_ready), .weight_ready(weight_ready), .result_ready(result_ready),
        .cpu_buf_sel(cpu_buf_sel), .cpu_buf_addr(cpu_buf_addr),
        .cpu_wdata(cpu_wdata), .cpu_rdata(cpu_rdata), .cpu_we(cpu_we), .cpu_re(cpu_re),
        .buffer_addr_inc(buffer_addr_inc),
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
        .eml_start(eml_start), .eml_opcode_o(eml_opcode_o),
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

endmodule
