`timescale 1ns/1ps
module pe_gemv_ws #(
    parameter integer N         = 4,
    parameter integer IN_WIDTH  = 8,
    parameter integer OUT_WIDTH = 16,
    parameter integer FRAC      = 0,
    parameter integer IDX_W     = (N <= 1) ? 1 : $clog2(N),
    parameter integer PE_ID     = 0
) (
    input  wire                         clk,
    input  wire                         rst_n,

    // Weight value for this cycle's multiply, supplied by a single weight
    // RAM shared across all P PEs in this row (see gemm_systolic_2d.v).
    // All PEs in a row read the same address on the same cycle since they
    // share identical compute_start/x_in_valid timing, so per-PE storage
    // here was pure duplication.
    input  wire signed [IN_WIDTH-1:0]   w_dout,

    // Control and Streaming Inputs (AXI4-Stream interface)
    input  wire                         compute_start,

    input  wire                         x_in_valid,
    input  wire signed [IN_WIDTH-1:0]   x_in,
    input  wire                         x_in_last,

    // Streaming Outputs (forwarded to the next PE in the chain)
    output wire                         x_out_valid,
    output wire signed [IN_WIDTH-1:0]   x_out,
    output wire                         x_out_last,

    // Result Output (asserted when row multiplication is complete)
    output reg                          y_out_valid,
    output reg  signed [OUT_WIDTH-1:0]  y_out
);

    // ------------------------------------------------------------------
    // Backpressure is dead in this integration: the top-level wrapper tied
    // y_out_ready to 1'b1 for every PE, and x_out_ready chained down to a
    // constant 1'b1 at the bottom row, so x_in_ready was provably always 1
    // and the pipeline never actually stalled. Rather than rely on the
    // synthesizer to prove that after flattening, the ready/valid
    // handshake ports have been removed from the interface entirely.
    // (If this PE is ever reused in a genuinely backpressured context,
    // reinstate the ready ports and gate the register enables below on a
    // real `stall` term.)
    // ------------------------------------------------------------------

    // Stage 1 Registers (Cycle 1: Fetch and Registration)
    reg signed [IN_WIDTH-1:0] x_reg1;
    reg                       valid_reg1;
    reg                       last_reg1;
    reg                       start_reg1;

    // Direct forwarding from Stage 1 registers to achieve 1-cycle systolic delay
    assign x_out_valid = valid_reg1;
    assign x_out       = x_reg1;
    assign x_out_last  = last_reg1;

    // Stage 2 Registers (Cycle 2: Fused Multiply-Accumulate)
    // The multiply and the accumulate-add are done combinationally in the
    // same cycle and registered once into `acc`, instead of registering the
    // raw product first (stage 2) and adding it into the accumulator a
    // cycle later (stage 3). This removes a whole register stage
    // (PROD_W bits + 3 control bits) and shortens the per-PE latency by one
    // cycle. It does not affect the row-to-row systolic delay, which is
    // driven entirely by the Stage 1 registers above.
    localparam integer PROD_W = 2 * IN_WIDTH;
    localparam integer ACC_W  = (PROD_W > OUT_WIDTH ? PROD_W : OUT_WIDTH) + IDX_W;
    reg signed [ACC_W-1:0] acc;

    wire signed [PROD_W-1:0] prod;
    assign prod = w_dout * x_reg1;

    wire signed [ACC_W-1:0] acc_eff;
    // Clear accumulator if starting a new row or if start_reg1 (first element) propagates down
    assign acc_eff = (compute_start || start_reg1) ? {ACC_W{1'b0}} : acc;

    // ------------------------------------------------------------------
    // Row Complete Arithmetic (Rounding & Saturation)
    // ------------------------------------------------------------------
    wire signed [ACC_W-1:0] sum;
    assign sum = acc_eff + {{(ACC_W - PROD_W){prod[PROD_W-1]}}, prod};

    // Convergent / Symmetric Rounding
    wire signed [ACC_W-1:0] rounded_sum;
    assign rounded_sum = (FRAC > 0) ? (sum + (1 << (FRAC-1))) : sum;

    // Shift to align to output format
    wire signed [ACC_W-1:0] shifted_sum;
    assign shifted_sum = (FRAC > 0) ? (rounded_sum >>> FRAC) : rounded_sum;

    // Saturation Logic to prevent wrap-around at OUT_WIDTH limits.
    // Cheap uniform-bits overflow test instead of two full ACC_W-wide magnitude
    // comparators: the value fits in OUT_WIDTH bits (two's complement) iff all
    // bits from the OUT_WIDTH-1 sign position up to the MSB are identical.
    // This collapses to a small AND/OR reduction tree instead of two subtractors.
    localparam integer EXTRA_W = ACC_W - OUT_WIDTH + 1;
    wire [EXTRA_W-1:0] extra_bits = shifted_sum[ACC_W-1 -: EXTRA_W];
    wire               ovf        = ~(&extra_bits) & (|extra_bits);
    wire               sign       = shifted_sum[ACC_W-1];

    reg signed [OUT_WIDTH-1:0] saturated_y;
    always @(*) begin
        if (ovf) begin
            saturated_y = sign ? {1'b1, {(OUT_WIDTH-1){1'b0}}} : {1'b0, {(OUT_WIDTH-1){1'b1}}};
        end else begin
            saturated_y = shifted_sum[OUT_WIDTH-1:0];
        end
    end

    // ------------------------------------------------------------------
    // Pipeline Sequential Control Logic
    // ------------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            x_reg1       <= {IN_WIDTH{1'b0}};
            valid_reg1   <= 1'b0;
            last_reg1    <= 1'b0;
            start_reg1   <= 1'b0;

            acc          <= {ACC_W{1'b0}};
        end else begin

            // Stream registration (Stage 1 input)
            x_reg1      <= x_in;
            valid_reg1  <= x_in_valid;
            last_reg1   <= x_in_last;
            start_reg1  <= compute_start;

            // Fused Multiply-Accumulate Registration
            if (valid_reg1) begin
                acc <= sum;
            end
        end
    end

    // Output Result Registration (single-cycle valid pulse)
    always @(posedge clk) begin
        if (!rst_n) begin
            y_out_valid <= 1'b0;
            y_out       <= {OUT_WIDTH{1'b0}};
        end else begin
            // Default: clear the one-cycle valid pulse from last time
            y_out_valid <= 1'b0;

            // Complete row multiplier outputs dot product
            if (valid_reg1 && last_reg1) begin
                y_out       <= saturated_y;
                y_out_valid <= 1'b1;
            end
        end
    end

// synthesis translate_off
    always @(posedge clk) begin
        if (rst_n) begin
            if (compute_start || start_reg1 || valid_reg1) begin
                $display("[DEBUG PE %0d] t=%0t, compute_start=%b, start_reg1=%b, valid_reg1=%b, x_in_valid=%b, acc=%0d, sum=%0d, prod=%0d",
                         PE_ID, $time, compute_start, start_reg1, valid_reg1, x_in_valid, acc, sum, prod);
            end
        end
    end
// synthesis translate_on

endmodule
