`timescale 1ns/1ps
// =====================================================
// ReLU Block - Plain Signed Integer (default INT16, WIDTH=16)
//
// Handshake:
//   start : pulse 1 cycle to load din and begin
//   busy  : high while the block is processing
//   valid : pulses high for 1 cycle when dout is ready
//
// Latency: 2 clock cycles from start to valid.
//   cycle 1 (posedge after start): input is latched, busy goes high
//   cycle 2 (next posedge): result computed, valid goes high, busy goes low
// =====================================================
module relu_int16 #(
    parameter WIDTH = 16   // total bit width
)(
    input  wire                    clk,
    input  wire                    rst,     // synchronous, active-high
    input  wire                    start,
    input  wire signed [WIDTH-1:0] din,
    output reg                     busy,
    output reg                     valid,
    output reg  signed [WIDTH-1:0] dout
);

    localparam IDLE = 1'b0, BUSY = 1'b1;

    reg                     state;
    reg signed [WIDTH-1:0]  din_reg;

    always @(posedge clk) begin
        if (rst) begin
            state   <= IDLE;
            busy    <= 1'b0;
            valid   <= 1'b0;
            dout    <= {WIDTH{1'b0}};
            din_reg <= {WIDTH{1'b0}};
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
                    // y = max(0, x) -- sign-bit check only
                    dout  <= (din_reg[WIDTH-1] == 1'b0) ? din_reg : {WIDTH{1'b0}};
                    valid <= 1'b1;
                    busy  <= 1'b0;
                    state <= IDLE;
                end

                default: state <= IDLE;
            endcase
        end
    end

endmodule
