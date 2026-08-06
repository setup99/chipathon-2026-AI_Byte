`timescale 1ns/1ps
// =====================================================
// Block Wrapper - mode-decoded composition of ALU(Q8.8) / ReLU / Pool,
// with an optional trailing Scale (->INT8) stage.
//
// Replaces the old mutually-exclusive block_sel scheme with three
// independent enable bits -- bias_en / relu_en / pool_en -- so a
// single transaction can run either one block alone, or one of two
// fixed composed pipelines:
//   ReLU -> Pool            (CONV post-path: relu_en=1, pool_en=1)
//   Bias ADD -> ReLU        (FC post-path:   bias_en=1, relu_en=1)
// exactly per the mode table below. Scale (INT16/Q8.8 -> INT8) is a
// separate optional final stage, controlled by scale_en, applied
// uniformly no matter which pipeline ran.
//
// The ALU is alu_q88 (Q8.8 fixed point) rather than alu_int16: ADD/SUB
// are bit-identical to plain integer add/sub either way (only MUL
// needs to know about the fractional point), which is what makes the
// same ALU usable both for standalone Q8.8 math AND for an FC bias add
// between an INT16 SA accumulator and a sign-extended INT8 bias.
//
// ---- Mode table (bias_en, relu_en, pool_en sampled with 1st word) ----
//  bias relu pool | Mode            | words | flow
//   0    0    0   | ALU             |  2    | alu_q88(alu_opcode) -> [scale]
//   0    1    0   | ReLU only       |  1    | ReLU -> [scale]
//   0    0    1   | Pool only       |  4    | Pool(pool_op) -> [scale]
//   0    1    1   | ReLU->Pool      |  4    | ReLU x4 -> Pool(pool_op) -> [scale]
//   1    0    0   | Bias ADD        |  2    | alu_q88 ADD(y,bias_ext) -> [scale]
//   1    1    0   | FC Bias->ReLU   |  2    | alu_q88 ADD -> ReLU -> [scale]
//   1    x    1   | (illegal combo) |  -    | pool_en is forced OFF whenever bias_en=1
//
// Rules (matching the spec exactly):
//   - Standalone ALU (alu_opcode-selected op) only runs when
//     bias_en=relu_en=pool_en=0.
//   - Whenever bias_en=1, the ALU always runs ADD (alu_opcode is
//     ignored/forced to ADD), Pool never runs, and ReLU is optional.
//   - Whenever bias_en=0 and (relu_en or pool_en) is set, the ALU
//     never runs standalone -- only the ReLU/Pool path.
//
// I/O is the same fully serial/streaming, valid/ready handshake as
// before, with no top-level `start`: the wrapper is idle until it has
// accepted the number of words its latched mode needs, then begins
// automatically.
// =====================================================
module block_wrapper #(
    parameter WIDTH       = 16,  // internal accumulator width (Q8.8 / INT16 container)
    parameter FRAC        = 8,   // Q8.8 fractional bits (ALU MUL rescale)
    parameter OUT_WIDTH   = 8,   // requantized output width (INT8)
    parameter SCALE_SHIFT = 8    // right-shift applied by the scale stage
)(
    input  wire                        clk,
    input  wire                        rst,        // synchronous, active-high

    // ---- mode/opcode select, sampled with the first input word ----
    input  wire                        bias_en,    // 1 = Bias ADD stage (FC post-path, before ReLU)
    input  wire                        relu_en,    // 1 = ReLU stage
    input  wire                        pool_en,    // 1 = 2x2 Pool stage (forced off whenever bias_en=1)
    input  wire [1:0]                  alu_opcode, // ALU: 00 ADD / 01 SUB / 10 MUL (standalone ALU mode only)
    input  wire                        pool_op,    // Pool: 0 MAX / 1 AVG
    input  wire                        scale_en,   // 1 = requantize the final result through Scale to INT8

    // ---- serial input stream: operands pushed one word at a time ----
    input  wire signed [WIDTH-1:0]     in_data,
    input  wire                        in_valid,
    output wire                        in_ready,

    // ---- serial output stream: one result per operation ----
    output reg  signed [WIDTH-1:0]     out_data16,   // valid when out_is_int8=0
    output reg  signed [OUT_WIDTH-1:0] out_data8,    // valid when out_is_int8=1
    output reg                         out_is_int8,
    output reg                         out_valid,
    input  wire                        out_ready,
    output reg                         out_overflow,

    output wire                        busy
);

    localparam [3:0] S_LOAD           = 4'd0,
                      S_DISPATCH       = 4'd1,
                      S_ALU_START      = 4'd2,
                      S_ALU_WAIT       = 4'd3,
                      S_RELU_START     = 4'd4,
                      S_RELU_WAIT      = 4'd5,
                      S_POOL_START     = 4'd6,
                      S_POOL_WAIT      = 4'd7,
                      S_SCALE_DISPATCH = 4'd8,
                      S_SCALE_WAIT     = 4'd9,
                      S_OUT_HOLD       = 4'd10;

    reg [3:0] state;
    reg [2:0] word_cnt;

    reg        bias_en_reg;
    reg        relu_en_reg;
    reg        pool_en_eff_reg;  // pool_en, forced 0 whenever bias_en=1
    reg [1:0]  alu_opcode_reg;
    reg        pool_op_reg;
    reg        scale_en_reg;

    reg signed [WIDTH-1:0] operand_reg [0:3];

    reg signed [WIDTH-1:0] mid_result;
    reg                    mid_overflow;

    reg [1:0] relu_loop_idx;    // which operand word ReLU is currently processing (Pool-feeding modes)
    reg       relu_src_is_mid;  // 1 = this ReLU call's input is mid_result (Bias->ReLU), not operand_reg[idx]

    integer i;

    // ---- how many operand words the currently-latched mode needs ----
    function [2:0] needed_words(input bias_en_f, input relu_en_f, input pool_en_eff_f);
        if (bias_en_f)
            needed_words = 3'd2;                 // Bias ADD / FC Bias->ReLU: y, bias_ext
        else if (pool_en_eff_f)
            needed_words = 3'd4;                  // Pool-only / ReLU->Pool: A,B,C,D
        else if (relu_en_f)
            needed_words = 3'd1;                  // ReLU-only: din
        else
            needed_words = 3'd2;                  // standalone ALU: A, B
    endfunction

    // Use the live inputs for the very first word (before latching),
    // the registered values for every word after that. pool_en is
    // forced off whenever bias_en is set (the illegal bias+pool combo).
    wire bias_en_eff0 = (word_cnt == 3'd0) ? bias_en : bias_en_reg;
    wire relu_en_eff0 = (word_cnt == 3'd0) ? relu_en : relu_en_reg;
    wire pool_en_eff0 = ((word_cnt == 3'd0) ? pool_en : pool_en_eff_reg) & ~bias_en_eff0;
    wire [2:0] needed_eff = needed_words(bias_en_eff0, relu_en_eff0, pool_en_eff0);

    assign in_ready = (state == S_LOAD) && (word_cnt < needed_eff);
    assign busy     = !(state == S_LOAD && word_cnt == 3'd0);

    // ReLU's input is either the ALU/bias sum (Bias->ReLU path) or the
    // operand word currently being processed (ReLU-only / ReLU->Pool loop).
    wire signed [WIDTH-1:0] relu_din = relu_src_is_mid ? mid_result : operand_reg[relu_loop_idx];

    // ---- sub-block control/status wires ----
    reg                      alu_start, relu_start, pool_start, scale_start;
    wire                     alu_busy, alu_valid;
    wire signed [WIDTH-1:0]  alu_result;
    wire                     alu_overflow;

    wire                     relu_busy, relu_valid;
    wire signed [WIDTH-1:0]  relu_dout;

    wire                     pool_busy, pool_valid;
    wire signed [WIDTH-1:0]  pool_out;

    wire                        scale_busy, scale_valid, scale_overflow;
    wire signed [OUT_WIDTH-1:0] scale_dout;

    // ---- the four datapath blocks (one instance each) ----
    alu_q88 #(.WIDTH(WIDTH), .FRAC(FRAC)) u_alu (
        .clk(clk), .rst(rst), .start(alu_start),
        .A(operand_reg[0]), .B(operand_reg[1]),
        .opcode(bias_en_reg ? 2'b00 : alu_opcode_reg),  // bias_en forces ADD
        .busy(alu_busy), .valid(alu_valid),
        .result(alu_result), .overflow(alu_overflow)
    );

    relu_int16 #(.WIDTH(WIDTH)) u_relu (
        .clk(clk), .rst(rst), .start(relu_start),
        .din(relu_din),
        .busy(relu_busy), .valid(relu_valid),
        .dout(relu_dout)
    );

    pool_int16 #(.WIDTH(WIDTH)) u_pool (
        .clk(clk), .rst(rst), .start(pool_start),
        .A(operand_reg[0]), .B(operand_reg[1]), .C(operand_reg[2]), .D(operand_reg[3]),
        .opcode(pool_op_reg),
        .busy(pool_busy), .valid(pool_valid),
        .out(pool_out)
    );

    scale_int16_to_int8 #(.WIDTH_IN(WIDTH), .WIDTH_OUT(OUT_WIDTH), .SHIFT(SCALE_SHIFT)) u_scale (
        .clk(clk), .rst(rst), .start(scale_start),
        .din(mid_result),
        .busy(scale_busy), .valid(scale_valid),
        .overflow(scale_overflow), .dout(scale_dout)
    );

    always @(posedge clk) begin
        if (rst) begin
            state           <= S_LOAD;
            word_cnt        <= 3'd0;
            bias_en_reg     <= 1'b0;
            relu_en_reg     <= 1'b0;
            pool_en_eff_reg <= 1'b0;
            alu_opcode_reg  <= 2'b00;
            pool_op_reg     <= 1'b0;
            scale_en_reg    <= 1'b0;
            mid_result      <= {WIDTH{1'b0}};
            mid_overflow    <= 1'b0;
            relu_loop_idx   <= 2'd0;
            relu_src_is_mid <= 1'b0;
            out_data16      <= {WIDTH{1'b0}};
            out_data8       <= {OUT_WIDTH{1'b0}};
            out_is_int8     <= 1'b0;
            out_valid       <= 1'b0;
            out_overflow    <= 1'b0;
            alu_start       <= 1'b0;
            relu_start      <= 1'b0;
            pool_start      <= 1'b0;
            scale_start     <= 1'b0;
            for (i = 0; i < 4; i = i + 1)
                operand_reg[i] <= {WIDTH{1'b0}};
        end else begin
            // 1-cycle control pulses: default low unless re-asserted below
            alu_start   <= 1'b0;
            relu_start  <= 1'b0;
            pool_start  <= 1'b0;
            scale_start <= 1'b0;

            case (state)
                // -------- load operand words one at a time --------
                S_LOAD: begin
                    if (in_valid && in_ready) begin
                        if (word_cnt == 3'd0) begin
                            bias_en_reg     <= bias_en;
                            relu_en_reg     <= relu_en;
                            pool_en_eff_reg <= pool_en & ~bias_en; // illegal combo -> pool forced off
                            alu_opcode_reg  <= alu_opcode;
                            pool_op_reg     <= pool_op;
                            scale_en_reg    <= scale_en;
                        end
                        operand_reg[word_cnt] <= in_data;
                        word_cnt <= word_cnt + 3'd1;

                        if (word_cnt + 3'd1 == needed_eff) begin
                            state <= S_DISPATCH;
                        end
                    end
                end

                // -------- decide which pipeline this operation runs --------
                S_DISPATCH: begin
                    if (bias_en_reg) begin
                        // Bias ADD, then optional ReLU (Pool never runs here)
                        relu_src_is_mid <= 1'b0;
                        state           <= S_ALU_START;
                    end else if (pool_en_eff_reg) begin
                        if (relu_en_reg) begin
                            // ReLU->Pool: 4x ReLU first, then Pool
                            relu_src_is_mid <= 1'b0;
                            relu_loop_idx   <= 2'd0;
                            state           <= S_RELU_START;
                        end else begin
                            // Pool only
                            state <= S_POOL_START;
                        end
                    end else if (relu_en_reg) begin
                        // ReLU only
                        relu_src_is_mid <= 1'b0;
                        relu_loop_idx   <= 2'd0;
                        state           <= S_RELU_START;
                    end else begin
                        // standalone ALU (alu_opcode_reg selects the op)
                        state <= S_ALU_START;
                    end
                end

                // -------- ALU: standalone op, or bias ADD --------
                S_ALU_START: begin
                    alu_start <= 1'b1;
                    state     <= S_ALU_WAIT;
                end

                S_ALU_WAIT: begin
                    if (alu_valid) begin
                        mid_result   <= alu_result;
                        mid_overflow <= alu_overflow;
                        if (bias_en_reg && relu_en_reg) begin
                            // FC Bias->ReLU: feed the sum straight into ReLU
                            relu_src_is_mid <= 1'b1;
                            state           <= S_RELU_START;
                        end else begin
                            state <= S_SCALE_DISPATCH;
                        end
                    end
                end

                // -------- ReLU: single word, the Bias->ReLU sum, or one
                //          iteration of the 4x ReLU->Pool loop --------
                S_RELU_START: begin
                    relu_start <= 1'b1;
                    state      <= S_RELU_WAIT;
                end

                S_RELU_WAIT: begin
                    if (relu_valid) begin
                        if (relu_src_is_mid) begin
                            // FC Bias->ReLU: done, overflow already latched from the ALU add
                            mid_result <= relu_dout;
                            state      <= S_SCALE_DISPATCH;
                        end else begin
                            operand_reg[relu_loop_idx] <= relu_dout; // overwrite in place
                            if (pool_en_eff_reg) begin
                                if (relu_loop_idx == 2'd3) begin
                                    state <= S_POOL_START;
                                end else begin
                                    relu_loop_idx <= relu_loop_idx + 2'd1;
                                    state         <= S_RELU_START;
                                end
                            end else begin
                                // ReLU-only mode: done
                                mid_result   <= relu_dout;
                                mid_overflow <= 1'b0;
                                state        <= S_SCALE_DISPATCH;
                            end
                        end
                    end
                end

                // -------- Pool: only reached with operand_reg already
                //          holding either the raw words or their ReLU'd
                //          versions --------
                S_POOL_START: begin
                    pool_start <= 1'b1;
                    state      <= S_POOL_WAIT;
                end

                S_POOL_WAIT: begin
                    if (pool_valid) begin
                        mid_result   <= pool_out;
                        mid_overflow <= 1'b0;
                        state        <= S_SCALE_DISPATCH;
                    end
                end

                // -------- final stage: optional Scale, or direct output --------
                S_SCALE_DISPATCH: begin
                    if (scale_en_reg) begin
                        scale_start <= 1'b1;
                        state       <= S_SCALE_WAIT;
                    end else begin
                        out_data16   <= mid_result;
                        out_is_int8  <= 1'b0;
                        out_overflow <= mid_overflow;
                        out_valid    <= 1'b1;
                        state        <= S_OUT_HOLD;
                    end
                end

                S_SCALE_WAIT: begin
                    if (scale_valid) begin
                        out_data8    <= scale_dout;
                        out_is_int8  <= 1'b1;
                        out_overflow <= mid_overflow | scale_overflow;
                        out_valid    <= 1'b1;
                        state        <= S_OUT_HOLD;
                    end
                end

                // -------- hold the result until the consumer accepts it --------
                S_OUT_HOLD: begin
                    if (out_valid && out_ready) begin
                        out_valid <= 1'b0;
                        word_cnt  <= 3'd0;
                        state     <= S_LOAD;
                    end
                end

                default: state <= S_LOAD;
            endcase
        end
    end

endmodule
