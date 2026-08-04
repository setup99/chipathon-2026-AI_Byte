// SPDX-FileCopyrightText: 2026 AI_BYTE / Chipathon 2026
// SPDX-License-Identifier: Apache-2.0
//
// chip_core — workshop-slot wrapper for AI_BYTE (ai_byte_top).
//
// Workshop bidir_PAD[19:0]:
//   [3:0]   addr[3:0]      host → chip
//   [11:4]  data[7:0]      bidirectional (core drives iff re & ~we)
//   [12]    we             host → chip
//   [13]    re             host → chip
//   [14]    irq            chip → host
//   [15]    done_o         chip → host
//   [16]    error_o        chip → host
//   [17:19] debug_state    chip → host

`default_nettype none

module chip_core #(
    parameter NUM_INPUT_PADS,
    parameter NUM_BIDIR_PADS,
    parameter NUM_ANALOG_PADS
)(
`ifdef USE_POWER_PINS
    inout  wire VDD,
    inout  wire VSS,
`endif

    input  wire clk,
    input  wire rst_n,

    input  wire [NUM_INPUT_PADS-1:0] input_in,
    output wire [NUM_INPUT_PADS-1:0] input_pu,
    output wire [NUM_INPUT_PADS-1:0] input_pd,

    input  wire [NUM_BIDIR_PADS-1:0] bidir_in,
    output wire [NUM_BIDIR_PADS-1:0] bidir_out,
    output wire [NUM_BIDIR_PADS-1:0] bidir_oe,
    output wire [NUM_BIDIR_PADS-1:0] bidir_cs,
    output wire [NUM_BIDIR_PADS-1:0] bidir_sl,
    output wire [NUM_BIDIR_PADS-1:0] bidir_ie,
    output wire [NUM_BIDIR_PADS-1:0] bidir_pu,
    output wire [NUM_BIDIR_PADS-1:0] bidir_pd,

    inout  wire [NUM_ANALOG_PADS-1:0] analog
);

    assign input_pu = '0;
    assign input_pd = '0;
    assign bidir_cs = '0;
    assign bidir_sl = '0;
    assign bidir_pu = '0;
    assign bidir_pd = '0;

    // synthesis translate_off
    initial begin
        if (NUM_BIDIR_PADS < 20)
            $error("AI_BYTE chip_core needs NUM_BIDIR_PADS>=20 (got %0d)", NUM_BIDIR_PADS);
    end
    // synthesis translate_on

    wire [3:0] host_addr = bidir_in[3:0];
    wire       host_we   = bidir_in[12];
    wire       host_re   = bidir_in[13];
    wire       data_drive = host_re & ~host_we;

    wire [7:0] data_bus;
    wire       irq_w, done_w, error_w;
    wire [2:0] debug_w;

    // data bus: pads supply value when host writes; core tri-state bus when reading
    genvar bi;
    generate
        for (bi = 0; bi < 8; bi = bi + 1) begin : g_dbus
            assign data_bus[bi] = data_drive ? 1'bz : bidir_in[4 + bi];
        end
    endgenerate

    // Pad OE / out tables
    assign bidir_oe[3:0]   = 4'b0;                 // addr in
    assign bidir_out[3:0]  = 4'b0;

    assign bidir_oe[11:4]  = {8{data_drive}};      // data bidir
    assign bidir_out[11:4] = data_bus;

    assign bidir_oe[12]    = 1'b0;                 // we in
    assign bidir_out[12]   = 1'b0;
    assign bidir_oe[13]    = 1'b0;                 // re in
    assign bidir_out[13]   = 1'b0;

    assign bidir_oe[14]    = 1'b1;                 // irq
    assign bidir_out[14]   = irq_w;
    assign bidir_oe[15]    = 1'b1;
    assign bidir_out[15]   = done_w;
    assign bidir_oe[16]    = 1'b1;
    assign bidir_out[16]   = error_w;
    assign bidir_oe[19:17] = 3'b111;
    assign bidir_out[19:17]= debug_w;

    // Extra bidir pads beyond 20 (other slots): force inputs
    generate
        if (NUM_BIDIR_PADS > 20) begin : g_extra
            assign bidir_oe[NUM_BIDIR_PADS-1:20]  = {(NUM_BIDIR_PADS-20){1'b0}};
            assign bidir_out[NUM_BIDIR_PADS-1:20] = {(NUM_BIDIR_PADS-20){1'b0}};
        end
    endgenerate

    assign bidir_ie = ~bidir_oe;

    wire _unused = &{1'b0, input_in};

    ai_byte_top u_ai_byte (
        .clk        (clk),
        .rst_n      (rst_n),
        .addr       (host_addr),
        .data       (data_bus),
        .we         (host_we),
        .re         (host_re),
        .irq        (irq_w),
        .done_o     (done_w),
        .error_o    (error_w),
        .debug_state(debug_w)
    );

endmodule

`default_nettype wire
