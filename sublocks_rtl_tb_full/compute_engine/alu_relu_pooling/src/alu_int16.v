`timescale 1ns/1ps
// =====================================================
// ALU Block - Plain Signed Integer (default INT16, WIDTH=16)
// AREA-OPTIMIZED VARIANT
//
// The previous version used a single combinational `A*B` operator for
// MUL, which synthesizes into a full WIDTHxWIDTH array of adders (by
// far the most expensive thing in this whole design). This version
// replaces that with a classic sequential shift-and-add multiplier:
// ONE shared (WIDTH+1)-bit adder/subtractor is time-multiplexed across
// every arithmetic step this block ever needs --
//   - direct ADD / SUB,
//   - computing |A| and |B| (sign/magnitude split for MUL),
//   - the WIDTH repeated shift-add accumulation steps of the multiply,
//   - and the final sign correction on a negative MUL result.
// Multiply now takes WIDTH+~3 cycles instead of 1, trading latency
// for a large cut in cell count -- worthwhile whenever latency isn't
// the constraint. Add/Sub keep the same 2-cycle latency as before.
//
// Opcode:
//   00 -> Add
//   01 -> Subtract
//   10 -> Multiply
//
// Handshake:
//   start : pulse 1 cycle to load A,B,opcode and begin
//   busy  : high while the block is processing
//   valid : pulses high for 1 cycle when result/overflow are ready
//
// Multiply algorithm (unsigned magnitude shift-and-add):
//   1. sign = A[MSB] ^ B[MSB]; magnitude inputs |A|, |B| are formed by
//      routing A (resp. B) through the shared adder configured to
//      negate exactly when that operand's sign bit is set.
//   2. A (WIDTH+1)-bit accumulator and a WIDTH-bit multiplier operand
//      are packed into one (2*WIDTH+1)-bit shift register. Each of
//      WIDTH iterations conditionally adds the multiplicand into the
//      accumulator (via the same shared adder) based on the current
//      LSB of the multiplier field, then shifts the whole register
//      right by one bit -- the standard textbook sequential multiplier.
//   3. The WIDTH*WIDTH-bit magnitude result is always non-negative, so
//      saturation against MAX_VAL/MIN_VAL reduces to a simple unsigned
//      magnitude compare; the sign is re-applied at the very end (one
//      more use of the shared adder to negate, only when sign=1).
// =====================================================
module alu_int16 #(
    parameter WIDTH = 16
)(
    input  wire                     clk,
    input  wire                     rst,      // synchronous, active-high
    input  wire                     start,
    input  wire signed [WIDTH-1:0]  A,
    input  wire signed [WIDTH-1:0]  B,
    input  wire        [1:0]        opcode,
    output reg                      busy,
    output reg                      valid,
    output reg  signed [WIDTH-1:0]  result,
    output reg                      overflow
);

    localparam OP_ADD = 2'b00, OP_SUB = 2'b01, OP_MUL = 2'b10;

    localparam signed [WIDTH-1:0] MAX_VAL = {1'b0, {(WIDTH-1){1'b1}}}; // 0111...1
    localparam signed [WIDTH-1:0] MIN_VAL = {1'b1, {(WIDTH-1){1'b0}}}; // 1000...0

    // Unsigned-magnitude saturation thresholds for the MUL path, each
    // zero-extended to the full 2*WIDTH-bit magnitude-product width.
    localparam [2*WIDTH-1:0] MAG_THRESH_POS = {{WIDTH{1'b0}}, MAX_VAL}; // 32767
    localparam [2*WIDTH-1:0] MAG_THRESH_NEG = {{WIDTH{1'b0}}, MIN_VAL}; // 32768 (MIN_VAL's bit pattern, read unsigned)

    localparam [3:0] S_IDLE     = 4'd0,
                      S_ADD      = 4'd1,
                      S_SUB      = 4'd2,
                      S_MUL_ABSA = 4'd3,
                      S_MUL_ABSB = 4'd4,
                      S_MUL_ITER = 4'd5,
                      S_MUL_SIGN = 4'd6,
                      S_INVALID  = 4'd7;

    reg [3:0] state;
    reg signed [WIDTH-1:0] A_reg, B_reg;
    reg [1:0] opcode_reg;

    // ---- multiply-specific state ----
    reg                        result_sign;   // sign_a ^ sign_b
    reg  [WIDTH-1:0]           multiplicand;  // |A|, held fixed through the iteration
    reg  [2*WIDTH:0]           shreg;         // {acc (WIDTH+1 bits), multiplier (WIDTH bits)}
    reg  [$clog2(WIDTH)-1:0]   iter_cnt;

    // ---- ONE shared (WIDTH+1)-bit adder/subtractor, time-multiplexed ----
    // adder_a/adder_b/adder_invert are the only place any operand ever
    // reaches this expression, so synthesis maps it to a single adder.
    reg  signed [WIDTH:0] adder_a, adder_b;
    reg                   adder_invert;   // 1 = compute a-b, 0 = compute a+b
    wire signed [WIDTH:0] adder_b_eff = adder_invert ? ~adder_b : adder_b;
    wire signed [WIDTH:0] adder_sum   = adder_a + adder_b_eff + adder_invert;

    always @(*) begin
        adder_a      = {(WIDTH+1){1'b0}};
        adder_b      = {(WIDTH+1){1'b0}};
        adder_invert = 1'b0;
        case (state)
            S_ADD: begin
                adder_a      = {A_reg[WIDTH-1], A_reg};
                adder_b      = {B_reg[WIDTH-1], B_reg};
                adder_invert = 1'b0;
            end
            S_SUB: begin
                adder_a      = {A_reg[WIDTH-1], A_reg};
                adder_b      = {B_reg[WIDTH-1], B_reg};
                adder_invert = 1'b1;
            end
            S_MUL_ABSA: begin
                // |A| = A>=0 ? A : (0-A); invert exactly when A is negative.
                adder_a      = {(WIDTH+1){1'b0}};
                adder_b      = {A_reg[WIDTH-1], A_reg};
                adder_invert = A_reg[WIDTH-1];
            end
            S_MUL_ABSB: begin
                adder_a      = {(WIDTH+1){1'b0}};
                adder_b      = {B_reg[WIDTH-1], B_reg};
                adder_invert = B_reg[WIDTH-1];
            end
            S_MUL_ITER: begin
                // Conditionally add the multiplicand into the current
                // (WIDTH+1)-bit accumulator half of the shift register.
                adder_a      = shreg[2*WIDTH:WIDTH];
                adder_b      = {1'b0, multiplicand};
                adder_invert = 1'b0;
            end
            S_MUL_SIGN: begin
                // Precompute -magnitude; only actually used if result_sign=1.
                adder_a      = {(WIDTH+1){1'b0}};
                adder_b      = {1'b0, shreg[WIDTH-1:0]};
                adder_invert = 1'b1;
            end
            default: begin
                adder_a      = {(WIDTH+1){1'b0}};
                adder_b      = {(WIDTH+1){1'b0}};
                adder_invert = 1'b0;
            end
        endcase
    end

    always @(posedge clk) begin
        if (rst) begin
            state        <= S_IDLE;
            busy         <= 1'b0;
            valid        <= 1'b0;
            result       <= {WIDTH{1'b0}};
            overflow     <= 1'b0;
            A_reg        <= {WIDTH{1'b0}};
            B_reg        <= {WIDTH{1'b0}};
            opcode_reg   <= 2'b00;
            result_sign  <= 1'b0;
            multiplicand <= {WIDTH{1'b0}};
            shreg        <= {(2*WIDTH+1){1'b0}};
            iter_cnt     <= {$clog2(WIDTH){1'b0}};
        end else begin
            valid <= 1'b0;

            case (state)
                // -------- accept a new operation --------
                S_IDLE: begin
                    if (start) begin
                        A_reg      <= A;
                        B_reg      <= B;
                        opcode_reg <= opcode;
                        busy       <= 1'b1;
                        case (opcode)
                            OP_ADD:  state <= S_ADD;
                            OP_SUB:  state <= S_SUB;
                            OP_MUL:  state <= S_MUL_ABSA;
                            default: state <= S_INVALID;
                        endcase
                    end
                end

                // -------- ADD: one shared-adder cycle --------
                S_ADD: begin
                    if (adder_sum > $signed({1'b0, MAX_VAL})) begin
                        result   <= MAX_VAL;
                        overflow <= 1'b1;
                    end else if (adder_sum < $signed({1'b1, MIN_VAL})) begin
                        result   <= MIN_VAL;
                        overflow <= 1'b1;
                    end else begin
                        result   <= adder_sum[WIDTH-1:0];
                        overflow <= 1'b0;
                    end
                    valid <= 1'b1;
                    busy  <= 1'b0;
                    state <= S_IDLE;
                end

                // -------- SUB: one shared-adder cycle --------
                S_SUB: begin
                    if (adder_sum > $signed({1'b0, MAX_VAL})) begin
                        result   <= MAX_VAL;
                        overflow <= 1'b1;
                    end else if (adder_sum < $signed({1'b1, MIN_VAL})) begin
                        result   <= MIN_VAL;
                        overflow <= 1'b1;
                    end else begin
                        result   <= adder_sum[WIDTH-1:0];
                        overflow <= 1'b0;
                    end
                    valid <= 1'b1;
                    busy  <= 1'b0;
                    state <= S_IDLE;
                end

                // -------- MUL step 1: |A| via the shared adder --------
                S_MUL_ABSA: begin
                    multiplicand <= adder_sum[WIDTH-1:0];
                    result_sign  <= A_reg[WIDTH-1] ^ B_reg[WIDTH-1];
                    state        <= S_MUL_ABSB;
                end

                // -------- MUL step 2: |B| via the shared adder, load shift reg --------
                S_MUL_ABSB: begin
                    shreg    <= {{(WIDTH+1){1'b0}}, adder_sum[WIDTH-1:0]};
                    iter_cnt <= 0;
                    state    <= S_MUL_ITER;
                end

                // -------- MUL step 3: WIDTH shift-and-add iterations --------
                S_MUL_ITER: begin
                    shreg <= {(shreg[0] ? adder_sum : shreg[2*WIDTH:WIDTH]), shreg[WIDTH-1:0]} >> 1;
                    if (iter_cnt == WIDTH - 1) begin
                        state <= S_MUL_SIGN;
                    end else begin
                        iter_cnt <= iter_cnt + 1'b1;
                    end
                end

                // -------- MUL step 4: apply sign, saturate, done --------
                S_MUL_SIGN: begin
                    if (!result_sign) begin
                        if (shreg[2*WIDTH-1:0] > MAG_THRESH_POS) begin
                            result   <= MAX_VAL;
                            overflow <= 1'b1;
                        end else begin
                            result   <= shreg[WIDTH-1:0];
                            overflow <= 1'b0;
                        end
                    end else begin
                        if (shreg[2*WIDTH-1:0] > MAG_THRESH_NEG) begin
                            result   <= MIN_VAL;
                            overflow <= 1'b1;
                        end else begin
                            result   <= adder_sum[WIDTH-1:0]; // = -magnitude
                            overflow <= 1'b0;
                        end
                    end
                    valid <= 1'b1;
                    busy  <= 1'b0;
                    state <= S_IDLE;
                end

                // -------- unsupported opcode: defined, harmless result --------
                S_INVALID: begin
                    result   <= {WIDTH{1'b0}};
                    overflow <= 1'b0;
                    valid    <= 1'b1;
                    busy     <= 1'b0;
                    state    <= S_IDLE;
                end

                default: state <= S_IDLE;
            endcase
        end
    end

endmodule
