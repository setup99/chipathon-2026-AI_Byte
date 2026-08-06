`timescale 1ns/1ps
module gemm_systolic_2d #(
    parameter integer M         = 4,
    parameter integer P         = 4,
    parameter integer N         = 4,
    parameter integer IN_WIDTH  = 8,
    parameter integer OUT_WIDTH = 16,
    parameter integer FRAC      = 0,

    // Row time-multiplexing factor: M logical rows are computed using only
    // M/ROW_REUSE physical PE rows, run ROW_REUSE times ("passes"). Trades
    // throughput (ROW_REUSE x more cycles) for area (roughly 1/ROW_REUSE x
    // the physical row hardware). Must divide M evenly; M/ROW_REUSE and
    // ROW_REUSE should both be powers of two so the logical<->physical row
    // mapping below is free bit-slicing rather than a real divider.
    parameter integer ROW_REUSE = 2,

    // Safe index widths
    parameter integer ROW_W  = (M <= 1) ? 1 : $clog2(M),
    parameter integer IDX_W  = (N <= 1) ? 1 : $clog2(N),
    parameter integer M_PHYS = M / ROW_REUSE,
    parameter integer PHYS_ROW_W = (M_PHYS <= 1) ? 1 : $clog2(M_PHYS),
    parameter integer PASS_W     = (ROW_REUSE <= 1) ? 1 : $clog2(ROW_REUSE),
    parameter integer WADDR_W    = IDX_W + PASS_W
) (
    input  wire                         clk,
    input  wire                         rst,

    // Control interface
    input  wire [3:0]                   op_sel,
    input  wire                         start,
    output reg                          busy,
    output reg                          done,

    // Weight Preload Interface. w_load_row still addresses all M *logical*
    // rows -- the external protocol is unchanged; internally it's split
    // into a physical-row select and a pass select (see GEN_ROW_WEIGHT).
    input  wire                         w_load,
    input  wire [ROW_W-1:0]             w_load_row,
    input  wire [IDX_W-1:0]             w_load_col,
    input  wire signed [IN_WIDTH-1:0]   w_load_data,

    // Parallel Input Vector Stream (fed cycle-by-cycle for N cycles per
    // pass; only pass 0 is driven externally -- see input replay buffer).
    input  wire [P*IN_WIDTH-1:0]        x_in_data,

    // Streamed Output: one logical row's P results per pulse. y_row_idx
    // still ranges over all M logical rows -- the external protocol is
    // unchanged regardless of ROW_REUSE.
    output reg  [ROW_W-1:0]             y_row_idx,
    output reg  [P*OUT_WIDTH-1:0]       y_row_data,
    output reg                          y_row_valid
);

    // ------------------------------------------------------------------
    // OP_SEL Opcode for Systolic Array
    // ------------------------------------------------------------------
    localparam [3:0] OP_CONV = 4'b0101; // 4x4 Systolic Convolution

    // ------------------------------------------------------------------
    // FSM States
    // ------------------------------------------------------------------
    localparam [1:0] ST_IDLE    = 2'b00,
                     ST_COMPUTE = 2'b01,
                     ST_WAIT    = 2'b10,
                     ST_DONE    = 2'b11;

    reg [1:0] state;
    reg [IDX_W-1:0]  count;
    reg [PASS_W-1:0] pass_idx;

    // Internal PE stream control
    reg pe_x_in_valid;
    reg pe_x_in_last;

    // PE outputs declared early to avoid use-before-declaration errors
    // (only M_PHYS physical rows now, not M -- see GEN_ROW below)
    wire                     pe_y_valid [0:M_PHYS-1][0:P-1];
    wire signed [OUT_WIDTH-1:0] pe_y_out [0:M_PHYS-1][0:P-1];

    // ------------------------------------------------------------------
    // Input Replay Buffer
    // ------------------------------------------------------------------
    // Row time-multiplexing needs every pass to see the same N x P input
    // matrix, but the external interface only streams it once. Pass 0
    // captures each cycle's x_in_data into this buffer as it streams by;
    // passes 1..ROW_REUSE-1 replay it back into physical row 0 instead of
    // reading x_in_data again, so the external stimulus is unchanged.
    reg signed [IN_WIDTH-1:0] x_buf [0:N-1][0:P-1];
    integer bc;
    always @(posedge clk) begin
        if (pass_idx == {PASS_W{1'b0}} && state == ST_COMPUTE) begin
            for (bc = 0; bc < P; bc = bc + 1) begin
                x_buf[count][bc] <= x_in_data[bc*IN_WIDTH +: IN_WIDTH];
            end
        end
    end

    // ------------------------------------------------------------------
    // FSM Logic
    // ------------------------------------------------------------------
    always @(posedge clk) begin
        if (rst) begin
            state         <= ST_IDLE;
            busy          <= 1'b0;
            done          <= 1'b0;
            count         <= {IDX_W{1'b0}};
            pass_idx      <= {PASS_W{1'b0}};
            pe_x_in_valid <= 1'b0;
            pe_x_in_last  <= 1'b0;
        end else begin
            done <= 1'b0; // Default done pulse

            case (state)
                ST_IDLE: begin
                    busy <= 1'b0;
                    // Trigger computation on OP_CONV (0101)
                    if (start && (op_sel == OP_CONV)) begin
                        state         <= ST_COMPUTE;
                        busy          <= 1'b1;
                        count         <= {IDX_W{1'b0}};
                        pass_idx      <= {PASS_W{1'b0}};
                        pe_x_in_valid <= 1'b1;
                        if (N == 1) begin
                            pe_x_in_last  <= 1'b1;
                        end else begin
                            pe_x_in_last  <= 1'b0;
                        end
                    end
                end

                ST_COMPUTE: begin
                    busy <= 1'b1;
                    if (count == N - 1) begin
                        state         <= ST_WAIT;
                        pe_x_in_valid <= 1'b0;
                        pe_x_in_last  <= 1'b0;
                    end else begin
                        count <= count + 1'b1;
                        pe_x_in_valid <= 1'b1;
                        if (count + 1'b1 == N - 1) begin
                            pe_x_in_last <= 1'b1;
                        end
                    end
                end

                ST_WAIT: begin
                    busy <= 1'b1;
                    // Trigger completion of this pass when the bottom
                    // physical row finishes (all columns are in sync, so
                    // pe_y_valid[M_PHYS-1][0] signifies pass-wide completion).
                    if (pe_y_valid[M_PHYS-1][0]) begin
                        if (pass_idx == ROW_REUSE - 1) begin
                            state <= ST_DONE;
                        end else begin
                            // Loop back for the next pass: replay the
                            // buffered input through the same physical
                            // rows, now reading the next block of weights.
                            pass_idx      <= pass_idx + 1'b1;
                            count         <= {IDX_W{1'b0}};
                            state         <= ST_COMPUTE;
                            pe_x_in_valid <= 1'b1;
                            if (N == 1) begin
                                pe_x_in_last <= 1'b1;
                            end else begin
                                pe_x_in_last <= 1'b0;
                            end
                        end
                    end
                end

                ST_DONE: begin
                    busy  <= 1'b0;
                    done  <= 1'b1;
                    state <= ST_IDLE;
                end

                default: state <= ST_IDLE;
            endcase
        end
    end

    // ------------------------------------------------------------------
    // Systolic Chain Interconnections (M_PHYS physical rows)
    // ------------------------------------------------------------------
    wire                     chain_valid [0:M_PHYS][0:P-1];
    wire                     chain_last  [0:M_PHYS][0:P-1];
    wire signed [IN_WIDTH-1:0] pe_chain_x [0:M_PHYS][0:P-1];

    genvar c;
    generate
        for (c = 0; c < P; c = c + 1) begin : GEN_COL_IN
            assign chain_valid[0][c] = pe_x_in_valid;
            assign chain_last[0][c]  = pe_x_in_last;
            // Pass 0 reads live external data; replay passes read the
            // buffered copy captured during pass 0 instead.
            assign pe_chain_x[0][c]  = (pass_idx == {PASS_W{1'b0}})
                                        ? x_in_data[c*IN_WIDTH +: IN_WIDTH]
                                        : x_buf[count][c];
        end
    endgenerate

    // ------------------------------------------------------------------
    // Self-Synchronizing Start Sequence Generator (only M_PHYS deep now)
    // ------------------------------------------------------------------
    wire pe_start_in;
    assign pe_start_in = (state == ST_COMPUTE && count == 0);

    reg [M_PHYS-1:0] start_pipe;
    integer p;
    always @(posedge clk) begin
        if (rst) begin
            start_pipe <= {M_PHYS{1'b0}};
        end else begin
            start_pipe[0] <= pe_start_in;
            for (p = 1; p < M_PHYS; p = p + 1) begin
                start_pipe[p] <= start_pipe[p-1];
            end
        end
    end

    wire [M_PHYS-1:0] pe_start;
    assign pe_start = (M_PHYS <= 1) ? pe_start_in : {start_pipe[M_PHYS-2:0], pe_start_in};

    // ------------------------------------------------------------------
    // Per-Physical-Row Shared Weight RAM
    // ------------------------------------------------------------------
    // Each physical row's RAM now holds ROW_REUSE separate N-entry weight
    // vectors (one per pass it will stand in for), addressed as
    // {pass_idx, row_j}. Logical row r maps to physical row (r % M_PHYS)
    // and pass (r / M_PHYS) via plain bit-slicing of w_load_row, since
    // M_PHYS and ROW_REUSE are powers of two.
    wire signed [IN_WIDTH-1:0] row_w_dout   [0:M_PHYS-1];
    wire        [IDX_W-1:0]    row_j_eff_arr[0:M_PHYS-1];

    genvar rr;
    generate
        for (rr = 0; rr < M_PHYS; rr = rr + 1) begin : GEN_ROW_WEIGHT
            if (rr == 0) begin : GEN_ROW0_COUNTER
                reg [IDX_W-1:0] row_j;
                assign row_j_eff_arr[0] = pe_start[0] ? {IDX_W{1'b0}} : row_j;

                always @(posedge clk) begin
                    if (rst) begin
                        row_j <= {IDX_W{1'b0}};
                    end else if (pe_start[0]) begin
                        row_j <= chain_valid[0][0] ? {{(IDX_W-1){1'b0}}, 1'b1} : {IDX_W{1'b0}};
                    end else if (chain_valid[0][0]) begin
                        row_j <= row_j_eff_arr[0] + 1'b1;
                    end
                end
            end else begin : GEN_ROWN_PROPAGATE
                reg [IDX_W-1:0] row_j_prop;
                assign row_j_eff_arr[rr] = row_j_prop;

                always @(posedge clk) begin
                    if (rst) begin
                        row_j_prop <= {IDX_W{1'b0}};
                    end else begin
                        row_j_prop <= row_j_eff_arr[rr-1];
                    end
                end
            end

            ram_sdp #(
                .ADDR_W(WADDR_W),
                .DATA_W(IN_WIDTH),
                .DEPTH(N * ROW_REUSE)
            ) u_row_weight_ram (
                .clk(clk),
                .we(w_load && (w_load_row[PHYS_ROW_W-1:0] == rr)),
                .addr_a({w_load_row[ROW_W-1:PHYS_ROW_W], w_load_col}),
                .din_a(w_load_data),
                .addr_b({pass_idx, row_j_eff_arr[rr]}),
                .dout_b(row_w_dout[rr])
            );
        end
    endgenerate

    // ------------------------------------------------------------------
    // Instantiate M_PHYS x P PE Grid (was M x P before time-multiplexing)
    // ------------------------------------------------------------------
    genvar r;
    generate
        for (r = 0; r < M_PHYS; r = r + 1) begin : GEN_ROW
            for (c = 0; c < P; c = c + 1) begin : GEN_COL
                pe_gemv_ws #(
                    .N(N),
                    .IN_WIDTH(IN_WIDTH),
                    .OUT_WIDTH(OUT_WIDTH),
                    .FRAC(FRAC),
                    .IDX_W(IDX_W),
                    .PE_ID(r * P + c)
                ) u_pe (
                    .clk(clk),
                    .rst(rst),

                    .w_dout(row_w_dout[r]),

                    .compute_start(pe_start[r]),

                    .x_in_valid(chain_valid[r][c]),
                    .x_in(pe_chain_x[r][c]),
                    .x_in_last(chain_last[r][c]),

                    .x_out_valid(chain_valid[r+1][c]),
                    .x_out(pe_chain_x[r+1][c]),
                    .x_out_last(chain_last[r+1][c]),

                    .y_out_valid(pe_y_valid[r][c]),
                    .y_out(pe_y_out[r][c])
                );
            end
        end
    endgenerate

    // ------------------------------------------------------------------
    // Streamed Row Output
    // ------------------------------------------------------------------
    // Routed out combinationally (PE y_out is already registered inside
    // the PE, so no extra top-level register is needed -- see pe_gemv_ws.v
    // and the earlier y_buf/y_mat removal). The logical row number is
    // reconstructed from the current pass index and the physical row that
    // just completed: logical_row = pass_idx * M_PHYS + physical_row.
    integer r_idx, c_idx;
    always @(*) begin
        y_row_valid = 1'b0;
        y_row_idx   = {ROW_W{1'b0}};
        y_row_data  = {(P*OUT_WIDTH){1'b0}};
        for (r_idx = 0; r_idx < M_PHYS; r_idx = r_idx + 1) begin
            if (pe_y_valid[r_idx][0]) begin
                y_row_valid = 1'b1;
                y_row_idx   = pass_idx * M_PHYS + r_idx;
                for (c_idx = 0; c_idx < P; c_idx = c_idx + 1) begin
                    y_row_data[c_idx*OUT_WIDTH +: OUT_WIDTH] = pe_y_out[r_idx][c_idx];
                end
            end
        end
    end

endmodule
