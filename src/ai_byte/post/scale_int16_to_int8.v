`timescale 1ns/1ps
// =====================================================
// Scale / Requantize Block
// Converts a wide accumulator (default INT16) down to a narrow
// output (default INT8) the way quantized inference pipelines do at the
// end of a layer: arithmetic right-shift by SHIFT bits, then saturate to
// the narrower signed range.
//
// WIDTH_IN  = input bit width  (default 16)
// WIDTH_OUT = output bit width (default 8)
// SHIFT     = right-shift amount before truncation to WIDTH_OUT
//             (default 8 = WIDTH_IN - WIDTH_OUT, which folds the full
//              INT16 range down so it maps cleanly onto INT8 without
//              ever needing to saturate)
//
// Handshake matches every other block in this set:
//   start : pulse 1 cycle to load din and begin
//   busy  : high while processing
//   valid : pulses high for 1 cycle when dout/overflow are ready
// Latency: 2 clock cycles from start to valid.
// =====================================================
module scale_int16_to_int8 #(
    parameter WIDTH_IN  = 16,
    parameter WIDTH_OUT = 8,
    parameter SHIFT     = 8
)(
    input  wire                         clk,
    input  wire                         rst_n,   // synchronous, active-low
    input  wire                         start,
    input  wire signed [WIDTH_IN-1:0]   din,
    output reg                          busy,
    output reg                          valid,
    output reg                          overflow,
    output reg  signed [WIDTH_OUT-1:0]  dout
);

    localparam IDLE = 1'b0, BUSY = 1'b1;

    // Saturation bounds computed at WIDTH_IN width so the compare never
    // needs ad-hoc sign-extension/concatenation tricks.
    localparam signed [WIDTH_IN-1:0] MAX_OUT = (1 <<< (WIDTH_OUT-1)) - 1;
    localparam signed [WIDTH_IN-1:0] MIN_OUT = -(1 <<< (WIDTH_OUT-1));

    reg                        state;
    reg signed [WIDTH_IN-1:0]  din_reg;

    wire signed [WIDTH_IN-1:0] shifted = din_reg >>> SHIFT;

    always @(posedge clk) begin
        if (!rst_n) begin
            state    <= IDLE;
            busy     <= 1'b0;
            valid    <= 1'b0;
            overflow <= 1'b0;
            dout     <= {WIDTH_OUT{1'b0}};
            din_reg  <= {WIDTH_IN{1'b0}};
        end else begin
            case (state)
                IDLE: begin
                    valid <= 1'b0;
                    if (start) begin
                        din_reg <= din;
                        busy    <= 1'b1;
                        state   <= BUSY;
                    end
                end

                BUSY: begin
                    if (shifted > MAX_OUT) begin
                        dout     <= MAX_OUT[WIDTH_OUT-1:0];
                        overflow <= 1'b1;
                    end else if (shifted < MIN_OUT) begin
                        dout     <= MIN_OUT[WIDTH_OUT-1:0];
                        overflow <= 1'b1;
                    end else begin
                        dout     <= shifted[WIDTH_OUT-1:0];
                        overflow <= 1'b0;
                    end
                    valid <= 1'b1;
                    busy  <= 1'b0;
                    state <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
