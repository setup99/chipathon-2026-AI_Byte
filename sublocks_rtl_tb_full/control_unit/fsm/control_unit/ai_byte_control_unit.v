`timescale 1ns / 1ps
//============================================================
// AI_BYTE Control Unit (compute-only, integration-ready)
//
// Same 8-state FSM as the teammate design, with CPU data/addr
// path removed. Sequences compute only; MMIF owns buffer R/W.
//
//   IDLE -> FETCH -> DECODE -> ISSUE -> EXEC -> WBACK -> DONE -> IDLE
//                              \-> ERROR ----------------------/^
//
// Must never generate memory addresses or perform SRAM accesses.
//============================================================

module ai_byte_control_unit
(
    input  wire             clk,
    input  wire             rst_n,

    //--------------------------------------------------
    // Register File
    //--------------------------------------------------
    input  wire             start_pulse,        // RF.start_pulse
    input  wire             soft_reset,          // RF.soft_reset_pulse
    input  wire             irq_clear,           // RF.irq_clear_pulse

    input  wire [3:0]       opcode_reg,          // RF.opcode_o
    input  wire [7:0]       config_reg,          // RF.config_o

    output wire [7:0]       status_o,            // {5'b0, BUSY, DONE, ERROR}
    output wire             irq,                 // done_o | error_o
    output reg              busy_o,
    output reg              done_o,
    output reg              error_o,

    // Pipeline enables to compute IPs (from latched CONFIG)
    output wire             relu_en,
    output wire             pool_en,
    output wire             pool_type,           // 0=MAX, 1=AVG

    //--------------------------------------------------
    // Buffer Controller
    //--------------------------------------------------
    output wire             bc_start,
    output wire             mode,                // 1 while compute transaction active
    output wire [2:0]       compute_unit,

    input  wire             busy,
    input  wire             done,
    input  wire             error,
    input  wire             act_ready,
    input  wire             weight_ready,
    input  wire             result_ready,

    output wire [2:0]       debug_state
);

    //========================================================
    // States (same names / encoding as teammate FSM)
    //========================================================
    localparam S_IDLE   = 3'd0;
    localparam S_FETCH  = 3'd1;
    localparam S_DECODE = 3'd2;
    localparam S_ISSUE  = 3'd3;
    localparam S_EXEC   = 3'd4;
    localparam S_WBACK  = 3'd5;
    localparam S_DONE   = 3'd6;
    localparam S_ERROR  = 3'd7;

    reg [2:0] state;
    reg [2:0] next_state;

    //========================================================
    // Latched control fields (FETCH) — no data / address
    //========================================================
    reg [3:0] opcode_lat;
    reg [7:0] config_lat;

    // Illegal opcodes: 0x5, 0xC-0xF
    wire illegal_opcode =
        (opcode_lat == 4'h5) ||
        (opcode_lat >= 4'hC);

    // Compute always needs all three buffers free
    wire resources_ready = act_ready && weight_ready && result_ready;

    //========================================================
    // State register
    //========================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= S_IDLE;
        else if (soft_reset)
            state <= S_IDLE;
        else
            state <= next_state;
    end

    //========================================================
    // Next-state logic
    //========================================================
    always @(*) begin
        next_state = state;
        case (state)
            S_IDLE:
                if (start_pulse)
                    next_state = S_FETCH;

            S_FETCH:
                next_state = S_DECODE;

            S_DECODE:
                if (illegal_opcode)
                    next_state = S_ERROR;
                else if (resources_ready)
                    next_state = S_ISSUE;
                // else poll (buffers not ready)

            S_ISSUE:
                next_state = S_EXEC;

            S_EXEC:
                if (error)
                    next_state = S_ERROR;
                else if (done)
                    next_state = S_WBACK;

            S_WBACK:
                next_state = S_DONE;

            S_DONE:
                if (irq_clear)
                    next_state = S_IDLE;

            S_ERROR:
                if (irq_clear)
                    next_state = S_IDLE;

            default:
                next_state = S_IDLE;
        endcase
    end

    //========================================================
    // FETCH latch
    //========================================================
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            opcode_lat <= 4'h0;
            config_lat <= 8'h0;
        end
        else if (soft_reset) begin
            opcode_lat <= 4'h0;
            config_lat <= 8'h0;
        end
        else if (state == S_FETCH) begin
            opcode_lat <= opcode_reg;
            config_lat <= config_reg;
        end
    end

    //========================================================
    // BC / pipeline outputs
    //========================================================
    // mode=1 only during active compute (IDLE/DONE/ERROR => 0 for MMIF)
    assign mode         = (state != S_IDLE) &&
                          (state != S_DONE) &&
                          (state != S_ERROR);
    assign compute_unit = opcode_lat[2:0];
    assign bc_start     = (state == S_ISSUE);

    assign relu_en   = config_lat[0];
    assign pool_en   = config_lat[1];
    assign pool_type = config_lat[2];

    //========================================================
    // STATUS / IRQ
    //========================================================
    assign status_o = {5'b0, busy_o, done_o, error_o};
    assign irq      = done_o | error_o;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy_o  <= 1'b0;
            done_o  <= 1'b0;
            error_o <= 1'b0;
        end
        else if (soft_reset) begin
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
