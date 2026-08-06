// ============================================================
//  eml_wrapper_q88_serial.v
//  SERIAL-SOFTMAX VARIANT of eml_wrapper_q88_shared_busy.v.
//
//  Identical to eml_wrapper_q88_shared_busy.v in every respect
//  (shared tile, busy/ready handshake, route_opcode fix) except
//  OP_SOFTMAX now uses eml_softmax_q88_serial instead of
//  eml_softmax_q88_rtn_shared:
//
//    - z_in (was MAX_N*W packed bus) -> single W-bit port + z_valid
//      strobe, one logit pushed per cycle (gaps allowed)
//    - softmax's streamed output now rides the SAME shared
//      `result`/`valid` ports every other opcode uses, instead of a
//      dedicated softmax_result/softmax_result_valid pair. For
//      OP_SOFTMAX, `valid` simply pulses once per streamed element
//      (n_in pulses total) with `result` carrying that element --
//      exactly like every other opcode's single valid pulse, just
//      n_in of them instead of one. No extra output ports needed.
//
//    Transaction *completion* (the signal that clears busy_reg so a
//    new `start` can be accepted) is tracked internally off each
//    block's own done/valid signal -- for softmax this is the
//    module's own `valid` (transaction-complete, coincident with the
//    LAST streamed element) rather than every individual element
//    pulse, so busy correctly stays asserted until all n_in elements
//    have been produced.
//
//  True softmax latency with this interface is 11*n_in+3 cycles
//  (measured directly), assuming back-to-back pushes -- versus the
//  packed-bus version's 8*n_in+3, since logits/results now arrive/
//  leave serially instead of all at once. See
//  eml_softmax_q88_serial.v's header for the full trade-off
//  writeup (128-bit bus removed entirely; parallel max-tree + 8
//  dedicated subtractors replaced by the shared ALU reused
//  serially).
//
//  OP_SIGMOID and OP_TANH share one eml_sigmoid_tanh_q88_shared FSM
//  (tanh(x) = 2*sigma(2x)-1 is the only relationship needed; see that
//  file's header), and OP_RECIP/OP_SQRT share one
//  eml_recip_sqrt_q88_shared FSM (same 3-step LNS pipeline, different
//  middle-step operand order/shift). Both pairs are selected by a
//  `mode` bit taken from the live opcode during the accept cycle --
//  same convention route_opcode already uses for the tile-select mux.
// ============================================================
`timescale 1ns/1ps

module eml_wrapper_q88_serial #(
    parameter W     = 16,
    parameter F     = 8,
    parameter MAX_N = 8
)(
    input  wire             clk,
    input  wire             rst_n,   // synchronous, active-low
    input  wire             start,
    input  wire [2:0]       opcode,

    input  wire signed [W-1:0]  x_in,

    input  wire [3:0]           n_in,
    input  wire signed [W-1:0]  z_in,
    input  wire                 z_valid,

    input  wire signed [W-1:0]  x_ext,
    input  wire        [W-1:0]  y_ext,
    input  wire                 sel_x,
    input  wire                 sel_y,

    output reg  signed [W-1:0]  result,
    output reg                  valid,
    output reg                  ovf,
    output reg                  n_err,

    output wire                 busy,
    output wire                 ready
);
    localparam OP_SIGMOID  = 3'b000;
    localparam OP_TANH     = 3'b001;
    localparam OP_RECIP    = 3'b010;
    localparam OP_SQRT     = 3'b011;
    localparam OP_SOFTMAX  = 3'b100;
    localparam OP_FEEDBACK = 3'b101;

    // ── busy/ready and the registered opcode ──────────────────
    reg        busy_reg;
    reg [2:0]  opcode_reg;
    assign busy  = busy_reg;
    assign ready = ~busy_reg;

    wire accept = start & ready;

    wire start_sigmoid  = accept && (opcode == OP_SIGMOID);
    wire start_tanh     = accept && (opcode == OP_TANH);
    wire start_sigtanh  = start_sigmoid | start_tanh;
    wire mode_sigtanh   = (opcode == OP_TANH);   // live, sampled only on start_sigtanh's cycle

    wire start_recip    = accept && (opcode == OP_RECIP);
    wire start_sqrt     = accept && (opcode == OP_SQRT);
    wire start_recipsqrt = start_recip | start_sqrt;
    wire mode_recipsqrt  = (opcode == OP_SQRT);  // live, sampled only on start_recipsqrt's cycle

    wire start_softmax  = accept && (opcode == OP_SOFTMAX);
    wire start_feedback = accept && (opcode == OP_FEEDBACK);

    // see eml_wrapper_q88_shared_busy.v for why this must be
    // live-opcode-during-accept, opcode_reg otherwise
    wire [2:0] route_opcode = accept ? opcode : opcode_reg;

    // ── the one shared tile ────────────────────────────────────
    reg  signed [W-1:0] tile_x_sel;
    reg         [W-1:0] tile_y_sel;
    wire signed [W-1:0] tile_out;
    wire                tile_ovf;

    eml_tile_q88 #(.W(W),.F(F)) u_shared_tile (
        .x(tile_x_sel), .y(tile_y_sel), .out(tile_out), .ovf(tile_ovf)
    );

    wire signed [W-1:0] sigtanh_eml_x,  recipsqrt_eml_x,  softmax_eml_x,  feedback_eml_x;
    wire        [W-1:0] sigtanh_eml_y,  recipsqrt_eml_y,  softmax_eml_y,  feedback_eml_y;

    always @(*) begin
        case (route_opcode)
            OP_SIGMOID:  begin tile_x_sel = sigtanh_eml_x;   tile_y_sel = sigtanh_eml_y;   end
            OP_TANH:     begin tile_x_sel = sigtanh_eml_x;   tile_y_sel = sigtanh_eml_y;   end
            OP_RECIP:    begin tile_x_sel = recipsqrt_eml_x; tile_y_sel = recipsqrt_eml_y; end
            OP_SQRT:     begin tile_x_sel = recipsqrt_eml_x; tile_y_sel = recipsqrt_eml_y; end
            OP_SOFTMAX:  begin tile_x_sel = softmax_eml_x;  tile_y_sel = softmax_eml_y;  end
            OP_FEEDBACK: begin tile_x_sel = feedback_eml_x; tile_y_sel = feedback_eml_y; end
            default:     begin tile_x_sel = {W{1'b0}};      tile_y_sel = {W{1'b0}};      end
        endcase
    end

    // ── OP_SIGMOID / OP_TANH (merged FSM) ───────────────────────
    wire signed [W-1:0] sigtanh_result;
    wire                sigtanh_valid, sigtanh_ovf;

    eml_sigmoid_tanh_q88_shared #(.W(W),.F(F)) u_sigtanh (
        .clk(clk), .rst_n(rst_n), .start(start_sigtanh), .mode(mode_sigtanh),
        .x_in(x_in),
        .result(sigtanh_result), .valid(sigtanh_valid), .ovf(sigtanh_ovf),
        .eml_x_out(sigtanh_eml_x), .eml_y_out(sigtanh_eml_y),
        .eml_out_in(tile_out), .eml_ovf_in(tile_ovf)
    );

    // ── OP_RECIP / OP_SQRT (merged FSM) ─────────────────────────
    wire signed [W-1:0] recipsqrt_result;
    wire                recipsqrt_valid, recipsqrt_ovf;

    eml_recip_sqrt_q88_shared #(.W(W),.F(F)) u_recipsqrt (
        .clk(clk), .rst_n(rst_n), .start(start_recipsqrt), .mode(mode_recipsqrt),
        .x_in(x_in[W-1:0]),
        .result(recipsqrt_result), .valid(recipsqrt_valid), .ovf(recipsqrt_ovf),
        .eml_x_out(recipsqrt_eml_x), .eml_y_out(recipsqrt_eml_y),
        .eml_out_in(tile_out), .eml_ovf_in(tile_ovf)
    );

    // ── OP_SOFTMAX (serial) ─────────────────────────────────────
    wire signed [W-1:0] softmax_result_w;
    wire                softmax_result_valid_w;
    wire                softmax_valid, softmax_ovf, softmax_n_err;

    eml_softmax_q88_serial #(.W(W),.F(F),.MAX_N(MAX_N)) u_softmax (
        .clk(clk), .rst_n(rst_n), .start(start_softmax),
        .n_in(n_in), .z_in(z_in), .z_valid(z_valid),
        .result(softmax_result_w), .result_valid(softmax_result_valid_w),
        .valid(softmax_valid), .ovf(softmax_ovf), .n_err(softmax_n_err),
        .eml_x_out(softmax_eml_x), .eml_y_out(softmax_eml_y),
        .eml_out_in(tile_out), .eml_ovf_in(tile_ovf)
    );

    // ── OP_FEEDBACK ────────────────────────────────────────────
    wire signed [W-1:0] feedback_result;
    wire                feedback_valid, feedback_ovf;

    eml_feedback_cell_q88_shared #(.W(W),.F(F)) u_feedback (
        .clk(clk), .rst_n(rst_n), .valid_in(start_feedback),
        .x_ext(x_ext), .y_ext(y_ext),
        .sel_x(sel_x), .sel_y(sel_y),
        .out(feedback_result), .ovf(feedback_ovf), .valid_out(feedback_valid),
        .eml_x_out(feedback_eml_x), .eml_y_out(feedback_eml_y),
        .eml_out_in(tile_out), .eml_ovf_in(tile_ovf)
    );

    // ── output mux: keyed off opcode_reg, not live opcode ──────
    // `result`/`valid` are shared by every opcode, including softmax:
    // for OP_SOFTMAX, `valid` simply pulses once per streamed element
    // (n_in pulses total) with `result` carrying that element -- no
    // separate softmax_result/softmax_result_valid ports needed.
    //
    // `done` is tracked alongside, off each block's own transaction-
    // complete signal, purely to drive busy_reg below -- for softmax
    // that's the module's own `valid` (coincident with the LAST
    // streamed element), so busy correctly stays asserted through all
    // n_in elemental valid pulses and only clears after the last one.
    reg done;

    always @(*) begin
        case (opcode_reg)
            OP_SIGMOID: begin
                result = sigtanh_result; valid = sigtanh_valid; ovf = sigtanh_ovf; n_err = 1'b0;
                done = sigtanh_valid;
            end
            OP_TANH: begin
                result = sigtanh_result; valid = sigtanh_valid; ovf = sigtanh_ovf; n_err = 1'b0;
                done = sigtanh_valid;
            end
            OP_RECIP: begin
                result = recipsqrt_result; valid = recipsqrt_valid; ovf = recipsqrt_ovf; n_err = 1'b0;
                done = recipsqrt_valid;
            end
            OP_SQRT: begin
                result = recipsqrt_result; valid = recipsqrt_valid; ovf = recipsqrt_ovf; n_err = 1'b0;
                done = recipsqrt_valid;
            end
            OP_SOFTMAX: begin
                // softmax_valid (module's own transaction-complete) is
                // OR'd in here because the immediate n_err-rejection
                // path pulses ONLY softmax_valid, never
                // softmax_result_valid_w (no element was produced to
                // stream out) -- everywhere else the two coincide on
                // the last element, so the OR changes nothing there.
                result = softmax_result_w; valid = softmax_result_valid_w | softmax_valid; ovf = softmax_ovf; n_err = softmax_n_err;
                done = softmax_valid;
            end
            OP_FEEDBACK: begin
                result = feedback_result; valid = feedback_valid; ovf = feedback_ovf; n_err = 1'b0;
                done = feedback_valid;
            end
            default: begin
                result = {W{1'b0}}; valid = 1'b0; ovf = 1'b0; n_err = 1'b0;
                done = 1'b0;
            end
        endcase
    end

    // ── busy/opcode_reg sequencing ─────────────────────────────
    always @(posedge clk) begin
        if (!rst_n) begin
            busy_reg   <= 1'b0;
            opcode_reg <= {3{1'b0}};
        end else begin
            if (accept) begin
                busy_reg   <= 1'b1;
                opcode_reg <= opcode;
            end else if (busy_reg && done) begin
                busy_reg <= 1'b0;
            end
        end
    end

endmodule
