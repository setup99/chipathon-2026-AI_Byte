module alu #(
    parameter WIDTH = 8
)(
    input  wire                  clk,
    input  wire                  rst,

    // Simple handshake
    input  wire                  valid,
    input  wire                  enable,
    output wire                  ready,

    input  wire [WIDTH-1:0]      a,
    input  wire [WIDTH-1:0]      b,
    input  wire [1:0]            op,

    output reg [(2*WIDTH)-1:0]   result,

    output reg                   zero,
    output reg                   negative,
    output reg                   carry,
    output reg                   overflow
);

assign ready = 1'b1;

//------------------------------------------------------
// Next-state signals
//------------------------------------------------------

reg [(2*WIDTH)-1:0] next_result;

reg next_zero;
reg next_negative;
reg next_carry;
reg next_overflow;

reg [WIDTH:0] add_temp;
reg [WIDTH:0] sub_temp;

//------------------------------------------------------
// Combinational ALU
//------------------------------------------------------

always @(*) begin

    next_result   = 0;
    next_zero     = 0;
    next_negative = 0;
    next_carry    = 0;
    next_overflow = 0;

    add_temp = 0;
    sub_temp = 0;

    case(op)

        //=========================
        // ADD
        //=========================
        2'b00: begin

            add_temp = {1'b0,a} + {1'b0,b};

            next_result = add_temp;

            next_carry = add_temp[WIDTH];

            next_overflow =
                (~(a[WIDTH-1]^b[WIDTH-1])) &
                (a[WIDTH-1]^add_temp[WIDTH-1]);

        end

        //=========================
        // SUB
        //=========================
        2'b01: begin

            sub_temp = {1'b0,a} - {1'b0,b};

            next_result = sub_temp;

            next_carry = sub_temp[WIDTH];

            next_overflow =
                (a[WIDTH-1]^b[WIDTH-1]) &
                (a[WIDTH-1]^sub_temp[WIDTH-1]);

        end

        //=========================
        // MUL
        //=========================
        2'b10: begin

            next_result = a * b;

            next_carry = 0;

            next_overflow =
                |next_result[(2*WIDTH)-1:WIDTH];

        end

        default: begin
            next_result = 0;
        end

    endcase

    next_zero = (next_result == 0);

    next_negative = next_result[WIDTH-1];

end

//------------------------------------------------------
// Registers
//------------------------------------------------------

always @(posedge clk or posedge rst) begin

    if(rst) begin

        result <= 0;

        zero <= 0;
        negative <= 0;
        carry <= 0;
        overflow <= 0;

    end

    else if(valid && enable) begin

        result <= next_result;

        zero <= next_zero;
        negative <= next_negative;
        carry <= next_carry;
        overflow <= next_overflow;

    end

end

endmodule
