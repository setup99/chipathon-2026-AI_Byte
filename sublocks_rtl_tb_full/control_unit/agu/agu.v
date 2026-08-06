`timescale 1ns / 1ps
//============================================================
// AI_BYTE Address Generation Unit (AGU)
//
// Version : V1.0 — Option A (Linear stream)
//
// Emits N address beats:
//   act_addr = weight_addr = result_addr = i
//   i = 0 .. N-1
//
// N = feature_cols_i (software programs stream length).
// CONV/FC and kernel/stride/pad are ignored in V1.
// Full sliding-window CONV is deferred.
//
// Protocol to Buffer Controller:
//   addr_valid / addr_ready handshake
//   agu_done asserted after last beat (held until agu_en falls)
//============================================================

module ai_byte_agu
#(
    parameter ADDR_W = 8
)
(
    input  wire                 clk,
    input  wire                 rst_n,
    input  wire                 soft_reset,

    input  wire                 agu_en,          // from Buffer Controller
    input  wire                 addr_ready,      // from Buffer Controller

    input  wire [7:0]           feature_cols_i,  // N = beat count

    output reg  [ADDR_W-1:0]    act_addr,
    output reg  [ADDR_W-1:0]    weight_addr,
    output reg  [ADDR_W-1:0]    result_addr,
    output reg                  addr_valid,
    output reg                  agu_done
);

    //========================================================
    // Local FSM
    //========================================================

    localparam S_IDLE   = 2'd0;
    localparam S_STREAM = 2'd1;
    localparam S_DONE   = 2'd2;

    reg [1:0] state;
    reg [1:0] next_state;

    reg [7:0] beat_idx;
    reg [7:0] beat_max;     // N captured at start

    wire fire = addr_valid & addr_ready;

    wire is_last = (beat_max == 8'd0) ? 1'b1 :
                   (beat_idx == (beat_max - 8'd1));

    //========================================================
    // State register
    //========================================================

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= S_IDLE;
        else if (soft_reset || !agu_en)
            state <= S_IDLE;
        else
            state <= next_state;
    end

    //========================================================
    // Next state
    //========================================================

    always @(*) begin
        next_state = state;
        case (state)
            S_IDLE: begin
                if (agu_en) begin
                    if (feature_cols_i == 8'd0)
                        next_state = S_DONE;
                    else
                        next_state = S_STREAM;
                end
            end
            S_STREAM: begin
                if (fire && is_last)
                    next_state = S_DONE;
            end
            S_DONE: begin
                // Hold until agu_en falls (handled by soft path above)
                next_state = S_DONE;
            end
            default: next_state = S_IDLE;
        endcase
    end

    //========================================================
    // Counters / outputs
    //========================================================

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            beat_idx     <= 8'd0;
            beat_max     <= 8'd0;
            act_addr     <= {ADDR_W{1'b0}};
            weight_addr  <= {ADDR_W{1'b0}};
            result_addr  <= {ADDR_W{1'b0}};
            addr_valid   <= 1'b0;
            agu_done     <= 1'b0;
        end
        else if (soft_reset || !agu_en) begin
            beat_idx     <= 8'd0;
            beat_max     <= 8'd0;
            act_addr     <= {ADDR_W{1'b0}};
            weight_addr  <= {ADDR_W{1'b0}};
            result_addr  <= {ADDR_W{1'b0}};
            addr_valid   <= 1'b0;
            agu_done     <= 1'b0;
        end
        else begin
            case (state)
                S_IDLE: begin
                    agu_done   <= 1'b0;
                    addr_valid <= 1'b0;
                    beat_idx   <= 8'd0;
                    if (agu_en) begin
                        beat_max <= feature_cols_i;
                        if (feature_cols_i != 8'd0) begin
                            // Prepare first beat (shown in STREAM)
                            act_addr    <= {ADDR_W{1'b0}};
                            weight_addr <= {ADDR_W{1'b0}};
                            result_addr <= {ADDR_W{1'b0}};
                        end
                    end
                end

                S_STREAM: begin
                    agu_done   <= 1'b0;
                    addr_valid <= 1'b1;
                    act_addr   <= beat_idx[ADDR_W-1:0];
                    weight_addr<= beat_idx[ADDR_W-1:0];
                    result_addr<= beat_idx[ADDR_W-1:0];

                    if (fire) begin
                        if (!is_last)
                            beat_idx <= beat_idx + 8'd1;
                    end
                end

                S_DONE: begin
                    addr_valid <= 1'b0;
                    agu_done   <= 1'b1;
                end

                default: begin
                    addr_valid <= 1'b0;
                    agu_done   <= 1'b0;
                end
            endcase
        end
    end

endmodule
