`timescale 1ns / 1ps
//============================================================
// AI_BYTE Control Unit v2 — sequencer FSM (intent only)
// IDLE→FETCH→DECODE→ISSUE→EXEC→WBACK→DONE (+ERROR)
//============================================================

module ai_byte_control_unit_v2
#(
    parameter ENABLE_SA         = 1,
    parameter ENABLE_MICROPROG  = 1,
    parameter ENABLE_SOFTMAX    = 1,
    parameter SOFTMAX_MAX_N     = 8
)
(
    input  wire             clk,
    input  wire             rst_n,

    input  wire             start_pulse,
    input  wire             soft_reset_n,   // active-low soft reset
    input  wire             irq_clear,

    input  wire [3:0]       opcode_reg,
    input  wire [7:0]       config_reg,
    input  wire [7:0]       softmax_n_reg,
    input  wire [7:0]       feature_cols_reg,

    output wire [7:0]       status_o,
    output wire             irq,
    output reg              busy_o,
    output reg              done_o,
    output reg              error_o,

    output wire             relu_en,
    output wire             pool_en,
    output wire             pool_type,
    output wire             bias_en,
    output wire             scale_en,
    output wire             eml_scale_en,

    output reg  [2:0]       compute_unit,
    output reg  [1:0]       alu_subop,
    output reg  [2:0]       eml_opcode,
    output wire [3:0]       softmax_n,
    output wire [7:0]       feature_cols,

    output wire             bc_start,
    output wire             mode,

    input  wire             busy,
    input  wire             done,
    input  wire             error,
    input  wire             act_ready,
    input  wire             weight_ready,
    input  wire             result_ready,

    output wire [2:0]       debug_state
);

    localparam S_IDLE   = 3'd0;
    localparam S_FETCH  = 3'd1;
    localparam S_DECODE = 3'd2;
    localparam S_ISSUE  = 3'd3;
    localparam S_EXEC   = 3'd4;
    localparam S_WBACK  = 3'd5;
    localparam S_DONE   = 3'd6;
    localparam S_ERROR  = 3'd7;

    localparam [2:0] CU_PIPELINE = 3'b000;
    localparam [2:0] CU_FC       = 3'b001;
    localparam [2:0] CU_ALU      = 3'b010;
    localparam [2:0] CU_EML      = 3'b011;
    localparam [2:0] CU_ILLEGAL  = 3'b111;

    reg [2:0] state, next_state;
    reg [3:0] opcode_lat;
    reg [7:0] config_lat;
    reg [7:0] softmax_n_lat;
    reg [7:0] feature_cols_lat;

    wire feature_cut =
        ((opcode_lat == 4'h0 || opcode_lat == 4'h1) && !ENABLE_SA) ||
        (opcode_lat == 4'hA && !ENABLE_SOFTMAX) ||
        (opcode_lat == 4'hB && !ENABLE_MICROPROG);

    wire illegal_opcode =
        (opcode_lat == 4'h5) || (opcode_lat >= 4'hC) || feature_cut;

    wire softmax_n_bad =
        (opcode_lat == 4'hA) &&
        ((softmax_n_lat[3:0] < 4'd2) ||
         (softmax_n_lat[3:0] > SOFTMAX_MAX_N[3:0]));

    wire decode_error = illegal_opcode || softmax_n_bad;

    wire resources_ready =
        (compute_unit == CU_EML) ?
            (act_ready && result_ready) :
            (act_ready && weight_ready && result_ready);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= S_IDLE;
        else if (!soft_reset_n)
            state <= S_IDLE;
        else
            state <= next_state;
    end

    always @(*) begin
        next_state = state;
        case (state)
            S_IDLE:   if (start_pulse) next_state = S_FETCH;
            S_FETCH:  next_state = S_DECODE;
            S_DECODE: if (decode_error) next_state = S_ERROR;
                      else if (resources_ready) next_state = S_ISSUE;
            S_ISSUE:  next_state = S_EXEC;
            S_EXEC:   if (error) next_state = S_ERROR;
                      else if (done) next_state = S_WBACK;
            S_WBACK:  next_state = S_DONE;
            S_DONE:   if (irq_clear) next_state = S_IDLE;
            S_ERROR:  if (irq_clear) next_state = S_IDLE;
            default:  next_state = S_IDLE;
        endcase
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            opcode_lat       <= 4'h0;
            config_lat       <= 8'h0;
            softmax_n_lat    <= 8'h0;
            feature_cols_lat <= 8'h0;
        end
        else if (!soft_reset_n) begin
            opcode_lat       <= 4'h0;
            config_lat       <= 8'h0;
            softmax_n_lat    <= 8'h0;
            feature_cols_lat <= 8'h0;
        end
        else if (state == S_FETCH) begin
            opcode_lat       <= opcode_reg;
            config_lat       <= config_reg;
            softmax_n_lat    <= softmax_n_reg;
            feature_cols_lat <= feature_cols_reg;
        end
    end

    always @(*) begin
        case (opcode_lat)
            4'h0:    compute_unit = CU_PIPELINE;
            4'h1:    compute_unit = CU_FC;
            4'h2, 4'h3, 4'h4: compute_unit = CU_ALU;
            4'h6, 4'h7, 4'h8, 4'h9, 4'hA, 4'hB: compute_unit = CU_EML;
            default: compute_unit = CU_ILLEGAL;
        endcase
    end

    always @(*) begin
        case (opcode_lat)
            4'h2: alu_subop = 2'b00;
            4'h3: alu_subop = 2'b01;
            4'h4: alu_subop = 2'b10;
            default: alu_subop = 2'b00;
        endcase
    end

    always @(*) begin
        case (opcode_lat)
            4'h6: eml_opcode = 3'b000;
            4'h7: eml_opcode = 3'b001;
            4'h8: eml_opcode = 3'b010;
            4'h9: eml_opcode = 3'b011;
            4'hA: eml_opcode = 3'b100;
            4'hB: eml_opcode = 3'b101;
            default: eml_opcode = 3'b000;
        endcase
    end

    assign softmax_n    = softmax_n_lat[3:0];
    assign feature_cols = feature_cols_lat;

    assign mode     = (state != S_IDLE) && (state != S_DONE) && (state != S_ERROR);
    assign bc_start = (state == S_ISSUE);

    assign relu_en      = config_lat[0];
    assign pool_en      = config_lat[1];
    assign pool_type    = config_lat[2];
    assign bias_en      = config_lat[3];
    assign scale_en     = config_lat[4];
    assign eml_scale_en = config_lat[5];

    assign status_o = {5'b0, busy_o, done_o, error_o};
    assign irq      = done_o | error_o;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy_o  <= 1'b0;
            done_o  <= 1'b0;
            error_o <= 1'b0;
        end
        else if (!soft_reset_n) begin
            busy_o  <= 1'b0;
            done_o  <= 1'b0;
            error_o <= 1'b0;
        end
        else begin
            busy_o <= busy ||
                      ((next_state != S_IDLE) &&
                       (next_state != S_DONE) &&
                       (next_state != S_ERROR));

            if (state != S_DONE && next_state == S_DONE) begin
                done_o  <= 1'b1;
                error_o <= 1'b0;
            end
            else if (state != S_ERROR && next_state == S_ERROR) begin
                error_o <= 1'b1;
                done_o  <= 1'b0;
            end
            else if (irq_clear) begin
                done_o  <= 1'b0;
                error_o <= 1'b0;
            end
        end
    end

    assign debug_state = state;

endmodule
