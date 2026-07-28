`timescale 1ns/1ps

module tb_alu;

parameter WIDTH=8;

reg clk;
reg rst;

reg valid;
reg enable;
wire ready;

reg [WIDTH-1:0] a;
reg [WIDTH-1:0] b;
reg [1:0] op;

wire [(2*WIDTH)-1:0] result;

wire zero;
wire negative;
wire carry;
wire overflow;

alu #(WIDTH) dut(

    .clk(clk),
    .rst(rst),

    .valid(valid),
    .enable(enable),
    .ready(ready),

    .a(a),
    .b(b),
    .op(op),

    .result(result),

    .zero(zero),
    .negative(negative),
    .carry(carry),
    .overflow(overflow)

);

always #5 clk=~clk;

task send;

input [7:0] ta;
input [7:0] tb;
input [1:0] top;

begin

    @(posedge clk);

    while(!ready)
        @(posedge clk);

    a <= ta;
    b <= tb;
    op <= top;

    valid <= 1;
    enable <= 1;

    @(posedge clk);

    valid <= 0;
    enable <= 0;

    @(posedge clk);

    $display("----------------------------------------");
    $display("A=%0d  B=%0d  OP=%b",ta,tb,top);
    $display("RESULT=%0d",result);
    $display("Z=%b N=%b C=%b V=%b",
              zero,
              negative,
              carry,
              overflow);

end

endtask

initial begin

    clk=0;
    rst=1;

    valid=0;
    enable=0;

    a=0;
    b=0;
    op=0;

    #20;

    rst=0;

    send(10,20,2'b00);

    send(40,12,2'b01);

    send(8,7,2'b10);

    send(25,25,2'b01);

    send(100,50,2'b00);

    send(8'hFF,8'h01,2'b00);

    #20;

    $finish;

end

endmodule
