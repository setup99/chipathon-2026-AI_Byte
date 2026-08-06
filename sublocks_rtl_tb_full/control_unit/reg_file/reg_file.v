`timescale 1ns / 1ps
//============================================================
// AI_BYTE Register File
//
// Version : V1.0
//
// Simple shared 8-bit configuration bank.
// Continuously broadcasts to FSM / AGU / Buffer Controller.
//
// V1 notes
// --------
// • One module, no FSM, no hierarchy
// • BUFFER_DATA is NOT stored here (MMIF → Buffer Controller)
// • CONTROL bits are pulse-only; CONTROL reads as 0x00
// • STATUS is an external mirror (status_i)
// • VERSION is hardwired 0x01
//============================================================

module ai_byte_reg_file
#(
    parameter DATA_W        = 8,
    parameter REG_ADDR_W    = 4,
    parameter BUFFER_ADDR_W = 8
)
(
    input  wire                         clk,
    input  wire                         rst_n,

    //--------------------------------------------------------
    // Memory-Mapped Interface
    // (BUFFER_DATA addr is routed elsewhere by MMIF)
    //--------------------------------------------------------
    input  wire [REG_ADDR_W-1:0]        reg_addr,
    input  wire                         reg_we,
    input  wire                         reg_re,
    input  wire [DATA_W-1:0]            reg_wdata,
    output wire [DATA_W-1:0]            reg_rdata,

    //--------------------------------------------------------
    // Status Logic
    //--------------------------------------------------------
    input  wire [DATA_W-1:0]            status_i,
    input  wire                         busy_i,

    //--------------------------------------------------------
    // Buffer Controller
    //--------------------------------------------------------
    input  wire                         buffer_addr_inc,

    //--------------------------------------------------------
    // Side-effect pulses (1 cycle)
    //--------------------------------------------------------
    output reg                          start_pulse,
    output reg                          soft_reset_pulse,
    output reg                          irq_clear_pulse,

    //--------------------------------------------------------
    // Continuous broadcast
    //--------------------------------------------------------
    output wire [3:0]                   opcode_o,
    output wire [DATA_W-1:0]            config_o,
    output wire [DATA_W-1:0]            buffer_select_o,
    output wire [BUFFER_ADDR_W-1:0]     buffer_addr_o,
    output wire [DATA_W-1:0]            feature_rows_o,
    output wire [DATA_W-1:0]            feature_cols_o,
    output wire [DATA_W-1:0]            input_channels_o,
    output wire [DATA_W-1:0]            output_channels_o
);

    //========================================================
    // Address map
    //========================================================

    localparam ADDR_CONTROL         = 4'h0;
    localparam ADDR_STATUS          = 4'h1;
    localparam ADDR_OPCODE          = 4'h2;
    localparam ADDR_CONFIG          = 4'h3;
    localparam ADDR_BUFFER_SELECT   = 4'h4;
    localparam ADDR_BUFFER_ADDR     = 4'h5;
    // ADDR_BUFFER_DATA           = 4'h6  — not stored in RF
    localparam ADDR_FEATURE_ROWS    = 4'h7;
    localparam ADDR_FEATURE_COLS    = 4'h8;
    localparam ADDR_INPUT_CHANNELS  = 4'h9;
    localparam ADDR_OUTPUT_CHANNELS = 4'hA;
    // 4'hB .. 4'hE reserved
    localparam ADDR_VERSION         = 4'hF;

    localparam [DATA_W-1:0] VERSION_ID = 8'h01;

    //========================================================
    // Storage
    //========================================================

    reg [3:0]               opcode_reg;
    reg [5:0]               config_reg;
    reg [DATA_W-1:0]        buffer_select_reg;
    reg [BUFFER_ADDR_W-1:0] buffer_addr_reg;
    reg [DATA_W-1:0]        feature_rows_reg;
    reg [DATA_W-1:0]        feature_cols_reg;
    reg [DATA_W-1:0]        input_channels_reg;
    reg [DATA_W-1:0]        output_channels_reg;

    //========================================================
    // Broadcast (continuous)
    //========================================================

    assign opcode_o          = opcode_reg;
    assign config_o          = {2'b00, config_reg};
    assign buffer_select_o   = buffer_select_reg;
    assign buffer_addr_o     = buffer_addr_reg;
    assign feature_rows_o    = feature_rows_reg;
    assign feature_cols_o    = feature_cols_reg;
    assign input_channels_o  = input_channels_reg;
    assign output_channels_o = output_channels_reg;

    //========================================================
    // Write + side-effect pulses + BUFFER_ADDR auto-inc
    //========================================================

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            opcode_reg          <= 4'h0;
            config_reg          <= 6'h0;
            buffer_select_reg   <= {DATA_W{1'b0}};
            buffer_addr_reg     <= {BUFFER_ADDR_W{1'b0}};
            feature_rows_reg    <= {DATA_W{1'b0}};
            feature_cols_reg    <= {DATA_W{1'b0}};
            input_channels_reg  <= {DATA_W{1'b0}};
            output_channels_reg <= {DATA_W{1'b0}};

            start_pulse         <= 1'b0;
            soft_reset_pulse    <= 1'b0;
            irq_clear_pulse     <= 1'b0;
        end
        else begin
            // Default: pulses are one cycle
            start_pulse      <= 1'b0;
            soft_reset_pulse <= 1'b0;
            irq_clear_pulse  <= 1'b0;

            // CPU write has priority over auto-increment
            if (reg_we) begin
                case (reg_addr)
                    ADDR_CONTROL: begin
                        // Pulse-only bits; no sticky CONTROL storage
                        if (reg_wdata[0] && !busy_i)
                            start_pulse <= 1'b1;
                        if (reg_wdata[1])
                            soft_reset_pulse <= 1'b1;
                        if (reg_wdata[2])
                            irq_clear_pulse <= 1'b1;
                    end

                    ADDR_OPCODE:
                        opcode_reg <= reg_wdata[3:0];

                    ADDR_CONFIG:
                        config_reg <= reg_wdata[5:0];

                    ADDR_BUFFER_SELECT:
                        buffer_select_reg <= reg_wdata;

                    ADDR_BUFFER_ADDR:
                        buffer_addr_reg <= reg_wdata[BUFFER_ADDR_W-1:0];

                    ADDR_FEATURE_ROWS:
                        feature_rows_reg <= reg_wdata;

                    ADDR_FEATURE_COLS:
                        feature_cols_reg <= reg_wdata;

                    ADDR_INPUT_CHANNELS:
                        input_channels_reg <= reg_wdata;

                    ADDR_OUTPUT_CHANNELS:
                        output_channels_reg <= reg_wdata;

                    default: ; // STATUS, BUFFER_DATA, RESERVED, VERSION
                endcase
            end
            else if (buffer_addr_inc) begin
                buffer_addr_reg <= buffer_addr_reg + 1'b1;
            end
        end
    end

    //========================================================
    // Combinational read mux
    //========================================================

    reg [DATA_W-1:0] rdata_mux;

    always @(*) begin
        case (reg_addr)
            ADDR_CONTROL:
                rdata_mux = {DATA_W{1'b0}};          // Option A: always 0

            ADDR_STATUS:
                rdata_mux = status_i;

            ADDR_OPCODE:
                rdata_mux = {4'h0, opcode_reg};

            ADDR_CONFIG:
                rdata_mux = {2'b00, config_reg};

            ADDR_BUFFER_SELECT:
                rdata_mux = buffer_select_reg;

            ADDR_BUFFER_ADDR:
                rdata_mux = buffer_addr_reg;

            ADDR_FEATURE_ROWS:
                rdata_mux = feature_rows_reg;

            ADDR_FEATURE_COLS:
                rdata_mux = feature_cols_reg;

            ADDR_INPUT_CHANNELS:
                rdata_mux = input_channels_reg;

            ADDR_OUTPUT_CHANNELS:
                rdata_mux = output_channels_reg;

            ADDR_VERSION:
                rdata_mux = VERSION_ID;

            default:
                rdata_mux = {DATA_W{1'b0}};          // RESERVED / BUFFER_DATA
        endcase
    end

    // Drive read data when reg_re is asserted (MMIF samples during read)
    assign reg_rdata = reg_re ? rdata_mux : {DATA_W{1'b0}};

endmodule
