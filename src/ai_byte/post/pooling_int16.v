`timescale 1ns/1ps
// =====================================================
// Pooling Block - Plain Signed Integer (default INT16, WIDTH=16)
//
// One unified module, selected by opcode:
//   opcode = 0 (POOL_MAX) -> Max Pooling  (2x2)
//   opcode = 1 (POOL_AVG) -> Average Pooling (2x2)
//
// Handshake:
//   start : pulse 1 cycle to load A,B,C,D,opcode and begin
//   busy  : high while the block is processing
//   valid : pulses high for 1 cycle when out is ready
//
// Latency: 2 clock cycles from start to valid (same timing
// as every other block in this set, so they drop into the
// same pipeline/controller without special-casing).
//
// Integer note:
//   Max pooling is a pure comparison -- result width/format
//   independent, no rescaling needed.
//   Average pooling sums 4 WIDTH-bit values (needs 2 guard
//   bits headroom) then arithmetic-shifts right by 2 to
//   divide by 4.
// =====================================================
module pool_int16 #(
    parameter WIDTH = 16
)(
    input  wire                    clk,
    input  wire                    rst_n,     // synchronous, active-low
    input  wire                    start,
    input  wire signed [WIDTH-1:0] A,
    input  wire signed [WIDTH-1:0] B,
    input  wire signed [WIDTH-1:0] C,
    input  wire signed [WIDTH-1:0] D,
    input  wire                    opcode,    // 0 = MAX, 1 = AVERAGE
    output reg                      busy,
    output reg                      valid,
    output reg  signed [WIDTH-1:0]  out
);

    localparam POOL_MAX = 1'b0;
    localparam POOL_AVG = 1'b1;
    localparam IDLE      = 1'b0, BUSY = 1'b1;

    reg                     state;
    reg signed [WIDTH-1:0]  A_reg, B_reg, C_reg, D_reg;
    reg                     opcode_reg;

    // ---- combinational compute from the registered operands ----
    wire signed [WIDTH-1:0] max1 = (A_reg > B_reg) ? A_reg : B_reg;
    wire signed [WIDTH-1:0] max2 = (C_reg > D_reg) ? C_reg : D_reg;
    wire signed [WIDTH-1:0] max_result = (max1 > max2) ? max1 : max2;

    // 2 guard bits are enough headroom for summing 4 WIDTH-bit signed values
    wire signed [WIDTH+1:0] sum = {{2{A_reg[WIDTH-1]}}, A_reg} +
                                  {{2{B_reg[WIDTH-1]}}, B_reg} +
                                  {{2{C_reg[WIDTH-1]}}, C_reg} +
                                  {{2{D_reg[WIDTH-1]}}, D_reg};
    wire signed [WIDTH-1:0] avg_result = sum[WIDTH+1:2]; // arithmetic >>2

    always @(posedge clk) begin
        if (!rst_n) begin
            state      <= IDLE;
            busy       <= 1'b0;
            valid      <= 1'b0;
            out        <= {WIDTH{1'b0}};
            A_reg      <= {WIDTH{1'b0}};
            B_reg      <= {WIDTH{1'b0}};
            C_reg      <= {WIDTH{1'b0}};
            D_reg      <= {WIDTH{1'b0}};
            opcode_reg <= 1'b0;
        end else begin
            case (state)
                IDLE: begin
                    valid <= 1'b0;
                    if (start) begin
                        A_reg      <= A;
                        B_reg      <= B;
                        C_reg      <= C;
                        D_reg      <= D;
                        opcode_reg <= opcode;
                        busy       <= 1'b1;
                        state      <= BUSY;
                    end
                end

                BUSY: begin
                    out   <= (opcode_reg == POOL_AVG) ? avg_result : max_result;
                    valid <= 1'b1;
                    busy  <= 1'b0;
                    state <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
