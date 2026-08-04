`timescale 1ns / 1ps
//============================================================
// AI_BYTE Buffer Controller
//
// Version : V1.0
//
// Responsibilities
// ----------------
// • CPU access to Activation / Weight / Result buffers
// • Stream Act/Weight to Compute Engine (AGU addresses)
// • Capture Compute Engine results into Result Buffer
// • Report busy / done / error / ready to FSM
//
// V1 notes
// --------
// • Datapath + tiny local FSM only (no submodules, no FIFO)
// • Mode 0 = CPU owns SRAM, Mode 1 = Compute owns SRAM
// • Completion: agu_done + drain of in-flight beats
//============================================================

module ai_byte_buffer_ctrl
#(
    parameter DATA_W         = 8,
    parameter BUFFER_ADDR_W  = 8,
    parameter BUFFER_DEPTH   = 256
)
(
    input  wire                         clk,
    input  wire                         rst_n,
    input  wire                         soft_reset,

    // CPU / MMIF
    input  wire [1:0]                   cpu_buf_sel,
    input  wire [BUFFER_ADDR_W-1:0]     cpu_buf_addr,
    input  wire [DATA_W-1:0]            cpu_wdata,
    output wire [DATA_W-1:0]            cpu_rdata,
    input  wire                         cpu_we,
    input  wire                         cpu_re,
    output reg                          buffer_addr_inc,

    // FSM
    input  wire                         bc_start,
    input  wire                         mode,            // 0=CPU, 1=Compute
    input  wire [2:0]                   compute_unit,    // unused in V1 datapath

    output wire                         busy,
    output wire                         done,
    output wire                         error,
    output wire                         act_ready,
    output wire                         weight_ready,
    output wire                         result_ready,

    // AGU
    output wire                         agu_en,
    input  wire [BUFFER_ADDR_W-1:0]     act_addr,
    input  wire [BUFFER_ADDR_W-1:0]     weight_addr,
    input  wire [BUFFER_ADDR_W-1:0]     result_addr,
    input  wire                         addr_valid,
    output wire                         addr_ready,
    input  wire                         agu_done,        // AGU finished address stream

    // Compute Engine
    output wire [DATA_W-1:0]            act_data,
    output wire                         act_valid,
    output wire [DATA_W-1:0]            weight_data,
    output wire                         weight_valid,
    input  wire [DATA_W-1:0]            result_data,
    input  wire                         result_valid,

    // Activation SRAM
    output wire [BUFFER_ADDR_W-1:0]     sram_act_addr,
    output wire [DATA_W-1:0]            sram_act_wdata,
    input  wire [DATA_W-1:0]            sram_act_rdata,
    output wire                         sram_act_we,
    output wire                         sram_act_ce,

    // Weight SRAM
    output wire [BUFFER_ADDR_W-1:0]     sram_wt_addr,
    output wire [DATA_W-1:0]            sram_wt_wdata,
    input  wire [DATA_W-1:0]            sram_wt_rdata,
    output wire                         sram_wt_we,
    output wire                         sram_wt_ce,

    // Result SRAM
    output wire [BUFFER_ADDR_W-1:0]     sram_res_addr,
    output wire [DATA_W-1:0]            sram_res_wdata,
    input  wire [DATA_W-1:0]            sram_res_rdata,
    output wire                         sram_res_we,
    output wire                         sram_res_ce
);

    //========================================================
    // Local FSM
    //========================================================

    localparam IDLE    = 2'd0;
    localparam CPU_ACC = 2'd1;
    localparam COMPUTE = 2'd2;
    localparam FINISH  = 2'd3;

    reg [1:0] state;
    reg [1:0] next_state;

    //========================================================
    // Internal registers
    //========================================================

    reg                       error_reg;
    reg                       done_int;
    reg                       agu_done_seen;

    // Stream pipeline (1-cycle SRAM read)
    reg                       stream_rd_pending;
    reg [DATA_W-1:0]          act_data_reg;
    reg [DATA_W-1:0]          weight_data_reg;
    reg                       act_valid_reg;
    reg                       weight_valid_reg;

    // Result address delay (matches: SRAM read -> stream -> compute valid)
    reg [BUFFER_ADDR_W-1:0]   res_addr_cap;     // captured on addr_fire
    reg [BUFFER_ADDR_W-1:0]   res_addr_stream;  // aligned with act_valid
    reg [BUFFER_ADDR_W-1:0]   res_addr_result;  // aligned with result_valid (NBA)

    // Outstanding beats: +1 addr_fire, -1 result write
    reg [BUFFER_ADDR_W:0]     pending_cnt;

    // Result write pulse (same cycle as result_valid, using delayed addr)
    wire                      result_write;

    wire                      addr_fire;
    wire                      cpu_access;
    wire                      cpu_act_we;
    wire                      cpu_wt_we;
    wire                      cpu_res_we;

    assign addr_fire = addr_valid & addr_ready;

    assign act_data     = act_data_reg;
    assign act_valid    = act_valid_reg;
    assign weight_data  = weight_data_reg;
    assign weight_valid = weight_valid_reg;

    //========================================================
    // State register
    //========================================================

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            state <= IDLE;
        else if (soft_reset)
            state <= IDLE;
        else
            state <= next_state;
    end

    //========================================================
    // Next-state
    //========================================================

    always @(*) begin
        next_state = state;
        case (state)
            IDLE: begin
                if ((mode == 1'b0) && (cpu_we || cpu_re))
                    next_state = CPU_ACC;
                else if ((mode == 1'b1) && bc_start)
                    next_state = COMPUTE;
            end
            CPU_ACC: begin
                next_state = IDLE;
            end
            COMPUTE: begin
                if (done_int)
                    next_state = FINISH;
            end
            FINISH: begin
                next_state = IDLE;
            end
            default: next_state = IDLE;
        endcase
    end

    //========================================================
    // Status
    //========================================================

    assign busy         = (state == COMPUTE);
    assign done         = (state == FINISH);
    assign error        = error_reg;

    assign act_ready    = (state != COMPUTE);
    assign weight_ready = (state != COMPUTE);
    assign result_ready = (state != COMPUTE);

    assign agu_en       = (state == COMPUTE);
    assign addr_ready   = (state == COMPUTE) && !agu_done_seen;

    //========================================================
    // CPU access helpers
    //========================================================

    assign cpu_access =
        (state == CPU_ACC) ||
        ((state == IDLE) && (mode == 1'b0) && (cpu_we || cpu_re));

    assign cpu_act_we = cpu_access && cpu_we && (cpu_buf_sel == 2'b00);
    assign cpu_wt_we  = cpu_access && cpu_we && (cpu_buf_sel == 2'b01);
    assign cpu_res_we = cpu_access && cpu_we && (cpu_buf_sel == 2'b10);

    //--------------------------------------------------------
    // CPU read mux
    //--------------------------------------------------------

    reg [DATA_W-1:0] cpu_rdata_reg;

    always @(*) begin
        case (cpu_buf_sel)
            2'b00:   cpu_rdata_reg = sram_act_rdata;
            2'b01:   cpu_rdata_reg = sram_wt_rdata;
            2'b10:   cpu_rdata_reg = sram_res_rdata;
            default: cpu_rdata_reg = {DATA_W{1'b0}};
        endcase
    end

    assign cpu_rdata = cpu_re ? cpu_rdata_reg : {DATA_W{1'b0}};

    //--------------------------------------------------------
    // Error: invalid BUFFER_SELECT only
    //--------------------------------------------------------

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            error_reg <= 1'b0;
        else if (soft_reset)
            error_reg <= 1'b0;
        else if (cpu_access && (cpu_buf_sel == 2'b11))
            error_reg <= 1'b1;
    end

    //--------------------------------------------------------
    // BUFFER_ADDR auto-increment pulse
    //--------------------------------------------------------

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            buffer_addr_inc <= 1'b0;
        else if (soft_reset)
            buffer_addr_inc <= 1'b0;
        else begin
            buffer_addr_inc <= 1'b0;
            if (cpu_access && (cpu_we || cpu_re))
                buffer_addr_inc <= 1'b1;
        end
    end

    //========================================================
    // Compute stream: capture AGU addr, read SRAM, forward
    //========================================================
    //
    // Cycle N  : addr_fire -> CE with live AGU address
    // Cycle N+1: latch rdata -> act/weight_valid to Compute Engine
    //

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stream_rd_pending <= 1'b0;
            act_data_reg      <= {DATA_W{1'b0}};
            weight_data_reg   <= {DATA_W{1'b0}};
            act_valid_reg     <= 1'b0;
            weight_valid_reg  <= 1'b0;
            res_addr_cap      <= {BUFFER_ADDR_W{1'b0}};
            res_addr_stream   <= {BUFFER_ADDR_W{1'b0}};
            res_addr_result   <= {BUFFER_ADDR_W{1'b0}};
        end
        else if (soft_reset || (state == IDLE)) begin
            stream_rd_pending <= 1'b0;
            act_valid_reg     <= 1'b0;
            weight_valid_reg  <= 1'b0;
        end
        else if (state == COMPUTE) begin
            // Issue SRAM read
            stream_rd_pending <= addr_fire;

            if (addr_fire)
                res_addr_cap <= result_addr;

            // Return streamed data (1-cycle after CE)
            if (stream_rd_pending) begin
                act_data_reg     <= sram_act_rdata;
                weight_data_reg  <= sram_wt_rdata;
                act_valid_reg    <= 1'b1;
                weight_valid_reg <= 1'b1;
                res_addr_stream  <= res_addr_cap;
                // Hold result addr for next-cycle result_valid (NBA safe)
                res_addr_result  <= res_addr_cap;
            end
            else begin
                act_valid_reg    <= 1'b0;
                weight_valid_reg <= 1'b0;
            end
        end
        else begin
            stream_rd_pending <= 1'b0;
            act_valid_reg     <= 1'b0;
            weight_valid_reg  <= 1'b0;
        end
    end

    assign result_write = (state == COMPUTE) && result_valid;

    // Next pending count (combinational) for same-cycle done check
    wire [BUFFER_ADDR_W:0] pending_next =
        pending_cnt
        + {{BUFFER_ADDR_W{1'b0}}, addr_fire}
        - {{BUFFER_ADDR_W{1'b0}}, result_write};

    wire agu_done_seen_next = agu_done_seen | agu_done;

    //========================================================
    // Completion: agu_done + drain in-flight beats
    //========================================================

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            agu_done_seen <= 1'b0;
            pending_cnt   <= {(BUFFER_ADDR_W+1){1'b0}};
            done_int      <= 1'b0;
        end
        else if (soft_reset || (state == IDLE) || (state == FINISH)) begin
            agu_done_seen <= 1'b0;
            pending_cnt   <= {(BUFFER_ADDR_W+1){1'b0}};
            done_int      <= 1'b0;
        end
        else if (state == COMPUTE) begin
            agu_done_seen <= agu_done_seen_next;
            pending_cnt   <= pending_next;

            // Done when AGU finished and pipeline fully drained
            done_int <= agu_done_seen_next &&
                        (pending_next == 0) &&
                        !addr_fire &&
                        !stream_rd_pending &&
                        !act_valid_reg &&
                        !result_write;
        end
        else begin
            done_int <= 1'b0;
        end
    end

    //========================================================
    // Mode mux — CPU vs Compute (no arbitration)
    //========================================================

    // Activation
    assign sram_act_addr  = (state == COMPUTE) ? act_addr :
                                                     cpu_buf_addr;
    assign sram_act_wdata = cpu_access ? cpu_wdata : {DATA_W{1'b0}};
    assign sram_act_we    = (state == COMPUTE) ? 1'b0 : cpu_act_we;
    assign sram_act_ce    = (state == COMPUTE) ? addr_fire : cpu_access;

    // Weight
    assign sram_wt_addr   = (state == COMPUTE) ? weight_addr :
                                                     cpu_buf_addr;
    assign sram_wt_wdata  = cpu_access ? cpu_wdata : {DATA_W{1'b0}};
    assign sram_wt_we     = (state == COMPUTE) ? 1'b0 : cpu_wt_we;
    assign sram_wt_ce     = (state == COMPUTE) ? addr_fire : cpu_access;

    // Result
    assign sram_res_addr  = (state == COMPUTE) ? res_addr_result :
                                                     cpu_buf_addr;
    assign sram_res_wdata = (state == COMPUTE) ? result_data :
                            (cpu_access ? cpu_wdata : {DATA_W{1'b0}});
    assign sram_res_we    = (state == COMPUTE) ? result_write : cpu_res_we;
    assign sram_res_ce    = (state == COMPUTE) ? result_write : cpu_access;

endmodule
