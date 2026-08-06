`timescale 1ns/1ps
// =====================================================
// ALU Block - Q8.8 Fixed Point (default WIDTH=16, FRAC=8)
// AREA-OPTIMIZED VARIANT (same design as alu_int16, extended for Q8.8)
//
// Same single-shared-adder, sequential shift-and-add multiplier as
// alu_int16 (see that file for the full rationale) -- the only
// difference here is the MUL path applies the Q8.8 rescale:
//   MUL = sat( (A * B) >>> FRAC )      // Q8.8 x Q8.8 -> Q8.8
// ADD and SUB are UNCHANGED from plain integer add/sub -- a Q8.8
// value's bit pattern adds/subtracts exactly like any other signed
// integer of the same width; only multiply needs to know about the
// fractional point. This also means this same ALU, with opcode=ADD,
// is bit-compatible with an INT16 (non-fixed-point) add -- e.g. for
// an FC bias add where one operand is an INT16 accumulator and the
// other is a sign-extended INT8 bias.
//
// Opcode:
//   00 -> Add
//   01 -> Subtract
//   10 -> Multiply (Q8.8 x Q8.8 -> Q8.8, rescaled by FRAC)
//
// Handshake:
//   start : pulse 1 cycle to load A,B,opcode and begin
//   busy  : high while the block is processing
//   valid : pulses high for 1 cycle when result/overflow are ready
//
// Multiply algorithm (unsigned magnitude shift-and-add + rescale):
//   1. sign = A[MSB] ^ B[MSB]; magnitude inputs |A|, |B| are formed by
//      routing A (resp. B) through the shared adder configured to
//      negate exactly when that operand's sign bit is set.
//   2. A (WIDTH+1)-bit accumulator and a WIDTH-bit multiplier operand
//      are packed into one (2*WIDTH+1)-bit shift register. Each of
//      WIDTH iterations conditionally adds the multiplicand into the
//      accumulator (via the same shared adder) based on the current
//      LSB of the multiplier field, then shifts the whole register
//      right by one bit -- the standard textbook sequential multiplier.
//      This produces the full-precision UNSIGNED magnitude product,
//      still in Q16.16 terms (2*FRAC fractional bits).
//   3. Rescale: shift the magnitude product right by FRAC bits to fold
//      Q16.16 back down to Q8.8, THEN saturate against MAX_VAL/MIN_VAL
//      (still a simple unsigned magnitude compare, since the rescaled
//      magnitude is always non-negative) and re-apply the sign (one
//      more use of the shared adder to negate, only when sign=1).
// =====================================================
module alu_q88 #(
    parameter WIDTH = 16,
    parameter FRAC  = 8
)(
    input  wire                     clk,
    input  wire                     rst_n,    // synchronous, active-low
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

    // Unsigned-magnitude saturation thresholds for the (already
    // FRAC-rescaled) MUL magnitude, zero-extended to 2*WIDTH bits.
    localparam [2*WIDTH-1:0] MAG_THRESH_POS = {{WIDTH{1'b0}}, MAX_VAL}; // 32767
    localparam [2*WIDTH-1:0] MAG_THRESH_NEG = {{WIDTH{1'b0}}, MIN_VAL}; // 32768 (MIN_VAL's bit pattern, read unsigned)

    localparam [3:0] S_IDLE     = 4'd0,
                      S_ADD      = 4'd1,
                      S_SUB      = 4'd2,
                      S_MUL_ABSA = 4'd3,
                      S_MUL_ABSB = 4'd4,
                      S_MUL_ITER = 4'd5,
                      S_MUL_SIGN = 4'd6,
                      S_MUL_ROUND= 4'd7,
                      S_INVALID  = 4'd8;

    reg [3:0] state;
    reg signed [WIDTH-1:0] A_reg, B_reg;
    reg [1:0] opcode_reg;

    // ---- multiply-specific state ----
    reg                        result_sign;   // sign_a ^ sign_b
    reg  [WIDTH-1:0]           multiplicand;  // |A|, held fixed through the iteration
    reg  [2*WIDTH:0]           shreg;         // {acc (WIDTH+1 bits), multiplier (WIDTH bits)}
    reg  [$clog2(WIDTH)-1:0]   iter_cnt;

    // Q8.8 rescale: fold the Q16.16 magnitude product back down to Q8.8
    // by dropping the low FRAC bits (unsigned value, so a logical shift
    // is exact -- no rounding is applied, matching sat((A*B)>>>FRAC)).
    wire [2*WIDTH-1:0] mag_shifted = shreg[2*WIDTH-1:0] >> FRAC;
    // Whether any of the FRAC bits being dropped were set -- needed to
    // correctly floor a NEGATIVE result (see S_MUL_SIGN/S_MUL_ROUND).
    wire mag_has_remainder = |shreg[FRAC-1:0];

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
                // Plain integer add -- no FRAC rescale (Q8.8 or INT16 both
                // just add bit patterns of the same width).
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
                // Precompute -(rescaled magnitude); only used if result_sign=1.
                adder_a      = {(WIDTH+1){1'b0}};
                adder_b      = {1'b0, mag_shifted[WIDTH-1:0]};
                adder_invert = 1'b1;
            end
            S_MUL_ROUND: begin
                // Floor-rounding correction: subtract 1 from the tentative
                // negated result (only entered when there was a dropped
                // fractional remainder on a negative result).
                adder_a      = {result[WIDTH-1], result};
                adder_b      = {{WIDTH{1'b0}}, 1'b1};
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
        if (!rst_n) begin
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

                // -------- ADD: one shared-adder cycle (no rescale) --------
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

                // -------- SUB: one shared-adder cycle (no rescale) --------
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

                // -------- MUL step 4: rescale by FRAC, apply sign, saturate --------
                S_MUL_SIGN: begin
                    if (!result_sign) begin
                        if (mag_shifted > MAG_THRESH_POS) begin
                            result   <= MAX_VAL;
                            overflow <= 1'b1;
                            valid    <= 1'b1;
                            busy     <= 1'b0;
                            state    <= S_IDLE;
                        end else begin
                            result   <= mag_shifted[WIDTH-1:0];
                            overflow <= 1'b0;
                            valid    <= 1'b1;
                            busy     <= 1'b0;
                            state    <= S_IDLE;
                        end
                    end else begin
                        if (mag_shifted > MAG_THRESH_NEG) begin
                            result   <= MIN_VAL;
                            overflow <= 1'b1;
                            valid    <= 1'b1;
                            busy     <= 1'b0;
                            state    <= S_IDLE;
                        end else begin
                            // Tentative truncate-toward-zero negation.
                            result   <= adder_sum[WIDTH-1:0]; // = -mag_shifted
                            overflow <= 1'b0;
                            if (mag_has_remainder) begin
                                // Dropped fractional bits on a negative
                                // result -- one more cycle to floor it
                                // correctly (subtract 1), not yet valid.
                                state <= S_MUL_ROUND;
                            end else begin
                                valid <= 1'b1;
                                busy  <= 1'b0;
                                state <= S_IDLE;
                            end
                        end
                    end
                end

                // -------- MUL step 5 (only when needed): floor correction --------
                S_MUL_ROUND: begin
                    if (result == MIN_VAL) begin
                        // Already at the most-negative representable value;
                        // one more step down is out of range -- saturate
                        // instead of wrapping.
                        result   <= MIN_VAL;
                        overflow <= 1'b1;
                    end else begin
                        result   <= adder_sum[WIDTH-1:0]; // = result - 1
                        overflow <= 1'b0;
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
