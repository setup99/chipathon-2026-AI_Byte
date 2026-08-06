`timescale 1ns / 1ps
//============================================================
// AI_BYTE Buffer Controller v2 — complete native CE jobs
//============================================================

module ai_byte_buffer_ctrl_v2
#(
    parameter DATA_W        = 8,
    parameter ACT_DEPTH     = 64,
    parameter WT_DEPTH      = 16,
    parameter RES_DEPTH     = 16,
    parameter TILE          = 4,
    parameter CNN_ACT_N     = TILE*TILE,
    parameter ENABLE_SA     = 1,
    parameter ENABLE_MICROPROG = 1,
    parameter ACT_ADDR_W    = (ACT_DEPTH<=1)?1:$clog2(ACT_DEPTH),
    parameter WT_ADDR_W     = (WT_DEPTH<=1)?1:$clog2(WT_DEPTH),
    parameter RES_ADDR_W    = (RES_DEPTH<=1)?1:$clog2(RES_DEPTH),
    parameter BUF_ADDR_W    = 8
)
(
    input  wire clk,
    input  wire rst_n,

    input  wire bc_start,
    input  wire mode,
    input  wire soft_reset_n,   // active-low soft reset
    input  wire [2:0] compute_unit,
    input  wire [1:0] alu_subop,
    input  wire [2:0] eml_opcode,
    input  wire [3:0] softmax_n,
    input  wire [7:0] feature_cols,
    input  wire relu_en, pool_en, pool_type, bias_en, scale_en, eml_scale_en,

    output reg  busy, done, error,
    output wire act_ready, weight_ready, result_ready,

    input  wire [1:0] cpu_buf_sel,
    input  wire [BUF_ADDR_W-1:0] cpu_buf_addr,
    input  wire [DATA_W-1:0] cpu_wdata,
    output reg  [DATA_W-1:0] cpu_rdata,
    input  wire cpu_we, cpu_re,
    output wire buffer_addr_inc,

    output reg  sram_act_ce, sram_act_we,
    output reg  [ACT_ADDR_W-1:0] sram_act_addr,
    output reg  [DATA_W-1:0] sram_act_wdata,
    input  wire [DATA_W-1:0] sram_act_rdata,

    output reg  sram_wt_ce, sram_wt_we,
    output reg  [WT_ADDR_W-1:0] sram_wt_addr,
    output reg  [DATA_W-1:0] sram_wt_wdata,
    input  wire [DATA_W-1:0] sram_wt_rdata,

    output reg  sram_res_ce, sram_res_we,
    output reg  [RES_ADDR_W-1:0] sram_res_addr,
    output reg  [DATA_W-1:0] sram_res_wdata,
    input  wire [DATA_W-1:0] sram_res_rdata,

    output reg  wrap_bias_en, wrap_relu_en, wrap_pool_en,
    output reg  [1:0] wrap_alu_opcode,
    output reg  wrap_pool_op, wrap_scale_en,
    output reg  signed [15:0] wrap_in_data,
    output reg  wrap_in_valid,
    input  wire wrap_in_ready,
    input  wire signed [15:0] wrap_out_data16,
    input  wire signed [7:0]  wrap_out_data8,
    input  wire wrap_out_is_int8, wrap_out_valid,
    output reg  wrap_out_ready,
    input  wire wrap_busy,

    output reg  eml_start,
    output reg  [2:0] eml_opcode_o,
    output reg  signed [15:0] eml_x_in,
    output reg  [3:0] eml_n_in,
    output reg  signed [15:0] eml_z_in,
    output reg  eml_z_valid,
    output reg  signed [15:0] eml_x_ext,
    output reg  [15:0] eml_y_ext,
    output reg  eml_sel_x, eml_sel_y,
    input  wire signed [15:0] eml_result,
    input  wire eml_valid, eml_ovf, eml_n_err, eml_busy, eml_ready,

    output reg  sa_start,
    output reg  [3:0] sa_op_sel,
    input  wire sa_busy, sa_done,
    output reg  sa_w_load,
    output reg  [1:0] sa_w_row, sa_w_col,
    output reg  signed [7:0] sa_w_data,
    output reg  [TILE*8-1:0] sa_x_in,
    input  wire [1:0] sa_y_row_idx,
    input  wire [TILE*16-1:0] sa_y_row_data,
    input  wire sa_y_row_valid
);

    localparam TILE_BYTES     = TILE*TILE;
    localparam SCRATCH_BYTES  = 2*TILE_BYTES;
    localparam FC_SCRATCH_BASE= SCRATCH_BYTES;
    localparam POOL_OUTS      = (TILE/2)*(TILE/2);

    localparam CU_PIPE=3'd0, CU_FC=3'd1, CU_ALU=3'd2, CU_EML=3'd3;
    localparam EML_SM=3'd4, EML_FB=3'd5;

    localparam ST_IDLE=5'd0, ST_ALU=5'd1, ST_EML=5'd2, ST_SM=5'd3, ST_MP=5'd4,
               ST_SAW=5'd5, ST_SAX=5'd6, ST_SAR=5'd7, ST_POST=5'd8,
               ST_DONE=5'd9, ST_ERR=5'd10;

    assign act_ready = 1'b1;
    assign weight_ready = 1'b1;
    assign result_ready = 1'b1;
    assign buffer_addr_inc = (!mode) && cpu_we;

    reg [4:0] st;
    reg [2:0] cu_l;
    reg [1:0] alu_l;
    reg [2:0] eml_l;
    reg [3:0] smn_l;
    reg [7:0] n_l;
    reg relu_l, pool_l, ptype_l, bias_l, scale_l, escale_l;

    reg [7:0] idx;
    reg [5:0] step;
    reg [DATA_W-1:0] lo;
    reg signed [15:0] Aq, Bq;
    reg signed [15:0] ybuf [0:TILE_BYTES-1];
    reg [7:0] rows_got;
    reg [7:0] win_i;
    reg mp_got;
    reg [7:0] instr;
    reg sm_started;
    reg [3:0] sm_wr;
    reg [3:0] sm_z;

    integer ii;

    // -------- CPU mux (combinational) --------
    always @(*) begin
        sram_act_ce=0; sram_act_we=0; sram_act_addr=0; sram_act_wdata=0;
        sram_wt_ce=0;  sram_wt_we=0;  sram_wt_addr=0;  sram_wt_wdata=0;
        sram_res_ce=0; sram_res_we=0; sram_res_addr=0; sram_res_wdata=0;
        cpu_rdata = 0;
        if (!mode) begin
            case (cpu_buf_sel)
                2'b00: begin
                    sram_act_ce=cpu_we|cpu_re; sram_act_we=cpu_we;
                    sram_act_addr=cpu_buf_addr[ACT_ADDR_W-1:0];
                    sram_act_wdata=cpu_wdata; cpu_rdata=sram_act_rdata;
                end
                2'b01: begin
                    sram_wt_ce=cpu_we|cpu_re; sram_wt_we=cpu_we;
                    sram_wt_addr=cpu_buf_addr[WT_ADDR_W-1:0];
                    sram_wt_wdata=cpu_wdata; cpu_rdata=sram_wt_rdata;
                end
                2'b10: begin
                    sram_res_ce=cpu_we|cpu_re; sram_res_we=cpu_we;
                    sram_res_addr=cpu_buf_addr[RES_ADDR_W-1:0];
                    sram_res_wdata=cpu_wdata; cpu_rdata=sram_res_rdata;
                end
                default: ;
            endcase
        end else begin
            sram_act_ce=m_act_ce; sram_act_we=m_act_we;
            sram_act_addr=m_act_addr; sram_act_wdata=m_act_wdata;
            sram_wt_ce=m_wt_ce; sram_wt_we=m_wt_we;
            sram_wt_addr=m_wt_addr; sram_wt_wdata=m_wt_wdata;
            sram_res_ce=m_res_ce; sram_res_we=m_res_we;
            sram_res_addr=m_res_addr; sram_res_wdata=m_res_wdata;
        end
    end

    reg m_act_ce, m_act_we, m_wt_ce, m_wt_we, m_res_ce, m_res_we;
    reg [ACT_ADDR_W-1:0] m_act_addr;
    reg [WT_ADDR_W-1:0]  m_wt_addr;
    reg [RES_ADDR_W-1:0] m_res_addr;
    reg [DATA_W-1:0] m_act_wdata, m_wt_wdata, m_res_wdata;

    function automatic signed [15:0] sext8;
        input [7:0] b;
        begin sext8 = {{8{b[7]}}, b}; end
    endfunction

    function automatic signed [15:0] prom8;
        input [7:0] b;
        begin prom8 = {b, 8'h00}; end
    endfunction

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st<=ST_IDLE; busy<=0; done<=0; error<=0;
            cu_l<=0; alu_l<=0; eml_l<=0; smn_l<=0; n_l<=1;
            relu_l<=0; pool_l<=0; ptype_l<=0; bias_l<=0; scale_l<=0; escale_l<=0;
            idx<=0; step<=0; lo<=0; Aq<=0; Bq<=0;
            wrap_bias_en<=0; wrap_relu_en<=0; wrap_pool_en<=0; wrap_alu_opcode<=0;
            wrap_pool_op<=0; wrap_scale_en<=0; wrap_in_data<=0; wrap_in_valid<=0; wrap_out_ready<=1;
            eml_start<=0; eml_opcode_o<=0; eml_x_in<=0; eml_n_in<=0;
            eml_z_in<=0; eml_z_valid<=0; eml_x_ext<=0; eml_y_ext<=0; eml_sel_x<=0; eml_sel_y<=0;
            sa_start<=0; sa_op_sel<=4'b0101; sa_w_load<=0; sa_w_row<=0; sa_w_col<=0; sa_w_data<=0; sa_x_in<=0;
            m_act_ce<=0; m_act_we<=0; m_wt_ce<=0; m_wt_we<=0; m_res_ce<=0; m_res_we<=0;
            m_act_addr<=0; m_wt_addr<=0; m_res_addr<=0;
            m_act_wdata<=0; m_wt_wdata<=0; m_res_wdata<=0;
            rows_got<=0; win_i<=0; mp_got<=0; instr<=0; sm_started<=0; sm_wr<=0; sm_z<=0;
            for (ii=0; ii<TILE_BYTES; ii=ii+1) ybuf[ii]<=0;
        end else if (!soft_reset_n) begin
            st<=ST_IDLE; busy<=0; done<=0; error<=0;
            wrap_in_valid<=0; eml_start<=0; sa_start<=0;
        end else begin
            // defaults each cycle
            done<=0; error<=0;
            wrap_in_valid<=0; eml_start<=0; eml_z_valid<=0;
            sa_start<=0; sa_w_load<=0;
            m_act_ce<=0; m_act_we<=0; m_wt_ce<=0; m_wt_we<=0; m_res_ce<=0; m_res_we<=0;
            busy <= (st!=ST_IDLE) && (st!=ST_DONE) && (st!=ST_ERR);

            if (eml_n_err && (st==ST_SM || st==ST_EML)) begin
                st <= ST_ERR;
            end

            case (st)
            ST_IDLE: begin
                if (bc_start) begin
                    cu_l<=compute_unit; alu_l<=alu_subop; eml_l<=eml_opcode;
                    smn_l<=softmax_n;
                    n_l<=(feature_cols==0)?8'd1:feature_cols;
                    relu_l<=relu_en; pool_l<=pool_en; ptype_l<=pool_type;
                    bias_l<=bias_en; scale_l<=scale_en; escale_l<=eml_scale_en;
                    idx<=0; step<=0; win_i<=0; rows_got<=0;
                    sm_started<=0; sm_wr<=0; sm_z<=0; mp_got<=0;
                    case (compute_unit)
                        CU_ALU: st<=ST_ALU;
                        CU_EML: begin
                            if (eml_opcode==EML_SM) st<=ST_SM;
                            else if (eml_opcode==EML_FB) st<= ENABLE_MICROPROG ? ST_MP : ST_ERR;
                            else st<=ST_EML;
                        end
                        CU_PIPE, CU_FC: st<= ENABLE_SA ? ST_SAW : ST_ERR;
                        default: st<=ST_ERR;
                    endcase
                end
            end

            // ---- ALU Q8.8: FEATURE_COLS pairs ----
            ST_ALU: begin
                wrap_bias_en<=0; wrap_relu_en<=0; wrap_pool_en<=0;
                wrap_alu_opcode<=alu_l; wrap_scale_en<=scale_l; wrap_out_ready<=1;
                case (step)
                    0: begin m_act_ce<=1; m_act_addr<={idx[5:0],1'b0}; step<=1; end
                    1: begin m_act_ce<=1; m_act_addr<={idx[5:0],1'b0}; step<=2; end // wait
                    2: begin lo<=sram_act_rdata; m_act_ce<=1; m_act_addr<={idx[5:0],1'b1}; step<=3; end
                    3: begin m_act_ce<=1; m_act_addr<={idx[5:0],1'b1}; step<=4; end
                    4: begin Aq<={sram_act_rdata,lo}; m_wt_ce<=1; m_wt_addr<={idx[2:0],1'b0}; step<=5; end
                    5: begin m_wt_ce<=1; m_wt_addr<={idx[2:0],1'b0}; step<=6; end
                    6: begin lo<=sram_wt_rdata; m_wt_ce<=1; m_wt_addr<={idx[2:0],1'b1}; step<=7; end
                    7: begin m_wt_ce<=1; m_wt_addr<={idx[2:0],1'b1}; step<=8; end
                    8: begin Bq<={sram_wt_rdata,lo}; step<=9; end
                    9: if (wrap_in_ready) begin
                        wrap_in_data<=Aq; wrap_in_valid<=1; step<=10;
                    end
                    10: if (wrap_in_ready) begin
                        wrap_in_data<=Bq; wrap_in_valid<=1; step<=11;
                    end
                    11: if (wrap_out_valid) begin
                        if (wrap_out_is_int8) begin
                            m_res_ce<=1; m_res_we<=1; m_res_addr<=idx[RES_ADDR_W-1:0];
                            m_res_wdata<=wrap_out_data8; step<=14;
                        end else begin
                            m_res_ce<=1; m_res_we<=1; m_res_addr<={idx[5:0],1'b0};
                            m_res_wdata<=wrap_out_data16[7:0]; step<=12;
                        end
                    end
                    12: begin m_res_ce<=1; m_res_we<=1; m_res_addr<={idx[5:0],1'b0}; step<=13; end
                    13: begin
                        m_res_ce<=1; m_res_we<=1; m_res_addr<={idx[5:0],1'b1};
                        m_res_wdata<=wrap_out_data16[15:8]; step<=14;
                    end
                    14: begin
                        if (idx+1 >= n_l) st<=ST_DONE;
                        else begin idx<=idx+1; step<=0; end
                    end
                    default: step<=0;
                endcase
            end

            // ---- EML scalar SQRT/RECIP or SIGMOID/TANH vector ----
            ST_EML: begin
                wrap_out_ready<=1;
                case (step)
                    0: begin
                        if (eml_l==3'b000 || eml_l==3'b001) begin
                            m_act_ce<=1; m_act_addr<=idx[ACT_ADDR_W-1:0]; step<=1;
                        end else begin
                            m_act_ce<=1; m_act_addr<={idx[5:0],1'b0}; step<=10;
                        end
                    end
                    1: begin m_act_ce<=1; m_act_addr<=idx[ACT_ADDR_W-1:0]; step<=2; end
                    2: begin
                        if (eml_ready && !eml_busy) begin
                            eml_start<=1; eml_opcode_o<=eml_l;
                            eml_x_in<=prom8(sram_act_rdata);
                            eml_n_in<=smn_l; step<=3;
                        end
                    end
                    3: if (eml_valid) begin
                        m_res_ce<=1; m_res_we<=1; m_res_addr<=idx[RES_ADDR_W-1:0];
                        begin : sat
                            reg signed [15:0] t;
                            t = eml_result >>> 8;
                            if (t > 127) m_res_wdata <= 8'sd127;
                            else if (t < -128) m_res_wdata <= -8'sd128;
                            else m_res_wdata <= t[7:0];
                        end
                        step<=4;
                    end
                    4: begin
                        if (idx+1 >= CNN_ACT_N[7:0] && (eml_l==3'b000||eml_l==3'b001))
                            st<=ST_DONE;
                        else if (idx+1 >= n_l && !(eml_l==3'b000||eml_l==3'b001))
                            st<=ST_DONE;
                        else begin idx<=idx+1; step<=0; end
                    end
                    10: begin m_act_ce<=1; m_act_addr<={idx[5:0],1'b0}; step<=11; end
                    11: begin m_act_ce<=1; m_act_addr<={idx[5:0],1'b0}; step<=12; end
                    12: begin lo<=sram_act_rdata; m_act_ce<=1; m_act_addr<={idx[5:0],1'b1}; step<=13; end
                    13: begin m_act_ce<=1; m_act_addr<={idx[5:0],1'b1}; step<=14; end
                    14: begin
                        if (eml_ready && !eml_busy) begin
                            eml_start<=1; eml_opcode_o<=eml_l;
                            eml_x_in<={sram_act_rdata,lo}; eml_n_in<=smn_l; step<=15;
                        end
                    end
                    15: if (eml_valid) begin
                        if (escale_l) begin
                            m_res_ce<=1; m_res_we<=1; m_res_addr<=idx[RES_ADDR_W-1:0];
                            begin : sat2
                                reg signed [15:0] t2;
                                t2 = eml_result >>> 8;
                                if (t2>127) m_res_wdata<=8'sd127;
                                else if (t2<-128) m_res_wdata<=-8'sd128;
                                else m_res_wdata<=t2[7:0];
                            end
                            step<=4;
                        end else begin
                            m_res_ce<=1; m_res_we<=1; m_res_addr<=0;
                            m_res_wdata<=eml_result[7:0]; Aq<=eml_result; step<=16;
                        end
                    end
                    16: begin m_res_ce<=1; m_res_we<=1; m_res_addr<=0; step<=17; end
                    17: begin
                        m_res_ce<=1; m_res_we<=1; m_res_addr<=1;
                        m_res_wdata<=Aq[15:8]; step<=4;
                    end
                    default: step<=0;
                endcase
            end

            // ---- Softmax ----
            ST_SM: begin
                if (!sm_started && eml_ready) begin
                    eml_start<=1; eml_opcode_o<=EML_SM; eml_n_in<=smn_l;
                    sm_started<=1; idx<=0; sm_z<=0; sm_wr<=0;
                end else if (sm_started) begin
                    if (sm_z < smn_l) begin
                        m_act_ce<=1; m_act_addr<=sm_z[ACT_ADDR_W-1:0];
                        // promote next cycle — use step
                        if (step==0) step<=1;
                        else begin
                            eml_z_in<=prom8(sram_act_rdata);
                            eml_z_valid<=1;
                            sm_z<=sm_z+1; step<=0;
                        end
                    end
                    if (eml_valid) begin
                        m_res_ce<=1; m_res_we<=1; m_res_addr<=sm_wr[RES_ADDR_W-1:0];
                        begin : sats
                            reg signed [15:0] ts;
                            ts = eml_result >>> 8;
                            if (ts>127) m_res_wdata<=8'sd127;
                            else if (ts<-128) m_res_wdata<=-8'sd128;
                            else m_res_wdata<=ts[7:0];
                        end
                        sm_wr<=sm_wr+1;
                        if (sm_wr+1 >= smn_l && !eml_busy) st<=ST_DONE;
                    end
                    if (!eml_busy && sm_started && sm_wr>=smn_l) st<=ST_DONE;
                end
            end

            // ---- Microprog FEEDBACK ----
            ST_MP: begin
                case (step)
                    0: begin m_act_ce<=1; m_act_addr<=idx[ACT_ADDR_W-1:0]; step<=1; end
                    1: begin m_act_ce<=1; m_act_addr<=idx[ACT_ADDR_W-1:0]; step<=2; end
                    2: begin instr<=sram_act_rdata; step<=3; end
                    3: begin m_wt_ce<=1; m_wt_addr<={instr[5:3],1'b0}; step<=4; end
                    4: begin m_wt_ce<=1; m_wt_addr<={instr[5:3],1'b0}; step<=5; end
                    5: begin lo<=sram_wt_rdata; m_wt_ce<=1; m_wt_addr<={instr[5:3],1'b1}; step<=6; end
                    6: begin m_wt_ce<=1; m_wt_addr<={instr[5:3],1'b1}; step<=7; end
                    7: begin
                        Aq<={sram_wt_rdata,lo};
                        m_wt_ce<=1; m_wt_addr<={instr[2:0],1'b0}; step<=8;
                    end
                    8: begin m_wt_ce<=1; m_wt_addr<={instr[2:0],1'b0}; step<=9; end
                    9: begin lo<=sram_wt_rdata; m_wt_ce<=1; m_wt_addr<={instr[2:0],1'b1}; step<=10; end
                    10: begin m_wt_ce<=1; m_wt_addr<={instr[2:0],1'b1}; step<=11; end
                    11: begin
                        if (eml_ready && !eml_busy) begin
                            eml_start<=1; eml_opcode_o<=EML_FB;
                            eml_x_ext<=Aq;
                            eml_y_ext<={sram_wt_rdata, lo};
                            eml_sel_x<=instr[7];
                            eml_sel_y<=instr[6];
                            step<=12;
                        end
                    end
                    12: if (eml_valid) begin
                        Aq<=eml_result;
                        if (idx+1 >= n_l) begin
                            m_res_ce<=1; m_res_we<=1; m_res_addr<=0;
                            m_res_wdata<=eml_result[7:0]; step<=13;
                        end else begin idx<=idx+1; step<=0; end
                    end
                    13: begin m_res_ce<=1; m_res_we<=1; m_res_addr<=0; step<=14; end
                    14: begin
                        m_res_ce<=1; m_res_we<=1; m_res_addr<=1;
                        m_res_wdata<=Aq[15:8]; st<=ST_DONE;
                    end
                    default: step<=0;
                endcase
            end

            // ---- SA weight preload ----
            ST_SAW: begin
                case (step)
                    0: begin m_wt_ce<=1; m_wt_addr<=idx[WT_ADDR_W-1:0]; step<=1; end
                    1: begin
                        sa_w_load<=1;
                        sa_w_row<=idx[3:2];
                        sa_w_col<=idx[1:0];
                        sa_w_data<=sram_wt_rdata;
                        if (idx+1 >= TILE_BYTES[7:0]) begin
                            idx<=0; step<=0; st<=ST_SAX;
                        end else begin idx<=idx+1; step<=0; end
                    end
                    default: step<=0;
                endcase
            end

            // ---- SA: buffer all X then stream N cycles ----
            ST_SAX: begin
                case (step)
                    0: begin // fill ybuf temporarily as byte scratch via Aq misuse — use dedicated: store in sa_x via multi
                        // Read Act[idx] into low bytes of ybuf as int8 in [7:0] of each — use Bq packing
                        m_act_ce<=1; m_act_addr<=idx[ACT_ADDR_W-1:0]; step<=1;
                    end
                    1: begin
                        // store act byte into scratch_i16 as zero-extended for reuse as X bytes
                        ybuf[idx] <= {{8{sram_act_rdata[7]}}, sram_act_rdata}; // keep int8 in low
                        if (idx+1 >= TILE_BYTES[7:0]) begin
                            idx<=0; step<=2;
                        end else begin idx<=idx+1; step<=0; end
                    end
                    2: begin
                        // present column 0 and start
                        sa_x_in <= {ybuf[3][7:0], ybuf[2][7:0], ybuf[1][7:0], ybuf[0][7:0]};
                        if (!sa_busy) begin
                            sa_start<=1; sa_op_sel<=4'b0101;
                            idx<=1; step<=3;
                        end
                    end
                    3: begin
                        // cycles 1..N-1
                        sa_x_in <= {
                            ybuf[idx*TILE+3][7:0],
                            ybuf[idx*TILE+2][7:0],
                            ybuf[idx*TILE+1][7:0],
                            ybuf[idx*TILE+0][7:0]
                        };
                        if (idx+1 >= TILE[7:0]) begin
                            idx<=0; rows_got<=0; step<=0; st<=ST_SAR;
                        end else idx<=idx+1;
                    end
                    default: step<=0;
                endcase
            end

            // ---- Collect SA rows ----
            ST_SAR: begin
                if (sa_y_row_valid) begin
                    ybuf[sa_y_row_idx*TILE + 0] <= sa_y_row_data[15:0];
                    ybuf[sa_y_row_idx*TILE + 1] <= sa_y_row_data[31:16];
                    ybuf[sa_y_row_idx*TILE + 2] <= sa_y_row_data[47:32];
                    ybuf[sa_y_row_idx*TILE + 3] <= sa_y_row_data[63:48];
                    rows_got <= rows_got + 1;
                end
                if (sa_done && (rows_got >= TILE[7:0] || sa_y_row_valid)) begin
                    // complete when done seen and enough rows (or last row this cycle)
                    if (sa_done && (rows_got + (sa_y_row_valid?1:0)) >= TILE[7:0]) begin
                        idx<=0; step<=0; win_i<=0; st<=ST_POST;
                    end
                end
            end

            // ---- Post: FC bias→relu→scale OR CONV relu→pool→scale ----
            ST_POST: begin
                wrap_out_ready<=1;
                if (cu_l==CU_FC) begin
                    wrap_bias_en<=bias_l; wrap_relu_en<=relu_l; wrap_pool_en<=0;
                    wrap_scale_en<=scale_l ? 1'b1 : 1'b1; // CNN FC → INT8
                    wrap_alu_opcode<=2'b00;
                    case (step)
                        0: begin
                            // bias byte
                            m_act_ce<=1; m_act_addr<=TILE_BYTES[ACT_ADDR_W-1:0]+idx[ACT_ADDR_W-1:0];
                            step<=1;
                        end
                        1: begin
                            Bq<=sext8(sram_act_rdata);
                            if (wrap_in_ready) begin
                                wrap_in_data<=ybuf[idx]; wrap_in_valid<=1; step<=2;
                            end
                        end
                        2: if (wrap_in_ready) begin
                            wrap_in_data<=Bq; wrap_in_valid<=1; step<=3;
                        end
                        3: if (wrap_out_valid) begin
                            m_res_ce<=1; m_res_we<=1; m_res_addr<=idx[RES_ADDR_W-1:0];
                            m_res_wdata<=wrap_out_is_int8 ? wrap_out_data8 : wrap_out_data16[7:0];
                            if (idx+1 >= TILE_BYTES[7:0]) st<=ST_DONE;
                            else begin idx<=idx+1; step<=0; end
                        end
                        default: step<=0;
                    endcase
                end else begin
                    // CONV: 4 windows of 2x2
                    wrap_bias_en<=0; wrap_relu_en<=relu_l; wrap_pool_en<=pool_l;
                    wrap_pool_op<=ptype_l; wrap_scale_en<=1;
                    // window win_i: map to 4 indices in 4x4
                    // win 0: (0,1,4,5), 1:(2,3,6,7), 2:(8,9,12,13), 3:(10,11,14,15)
                    case (step)
                        0: if (wrap_in_ready) begin
                            wrap_in_data<=ybuf[win_coords(win_i,0)]; wrap_in_valid<=1; step<=1;
                        end
                        1: if (wrap_in_ready) begin
                            wrap_in_data<=ybuf[win_coords(win_i,1)]; wrap_in_valid<=1; step<=2;
                        end
                        2: if (wrap_in_ready) begin
                            wrap_in_data<=ybuf[win_coords(win_i,2)]; wrap_in_valid<=1; step<=3;
                        end
                        3: if (wrap_in_ready) begin
                            wrap_in_data<=ybuf[win_coords(win_i,3)]; wrap_in_valid<=1; step<=4;
                        end
                        4: if (wrap_out_valid) begin
                            m_res_ce<=1; m_res_we<=1; m_res_addr<=win_i[RES_ADDR_W-1:0];
                            m_res_wdata<=wrap_out_data8;
                            if (win_i+1 >= POOL_OUTS[7:0]) st<=ST_DONE;
                            else begin win_i<=win_i+1; step<=0; end
                        end
                        default: step<=0;
                    endcase
                end
            end

            ST_DONE: begin done<=1; st<=ST_IDLE; end
            ST_ERR:  begin error<=1; st<=ST_IDLE; end
            default: st<=ST_IDLE;
            endcase
        end
    end

    function automatic [7:0] win_coords;
        input [7:0] w;
        input [1:0] k;
        reg [7:0] r0, c0;
        begin
            r0 = {w[1], 1'b0}; // 0 or 2
            c0 = {w[0], 1'b0};
            case (k)
                2'd0: win_coords = (r0<<2) + c0;
                2'd1: win_coords = (r0<<2) + c0 + 1;
                2'd2: win_coords = ((r0+1)<<2) + c0;
                default: win_coords = ((r0+1)<<2) + c0 + 1;
            endcase
        end
    endfunction

endmodule
