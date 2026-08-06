`ifndef RAM_SDP_V
`define RAM_SDP_V

module ram_sdp #(
    parameter integer ADDR_W = 4,
    parameter integer DATA_W = 16,
    parameter integer DEPTH  = 16
) (
    input  wire                 clk,

    // Port A: Write-only (Weight preloading)
    input  wire                 we,
    input  wire [ADDR_W-1:0]    addr_a,
    input  wire [DATA_W-1:0]    din_a,

    // Port B: Read-only (Sequential streaming for compute)
    input  wire [ADDR_W-1:0]    addr_b,
    output reg  [DATA_W-1:0]    dout_b
);

    // RAM array declaration
    reg [DATA_W-1:0] ram [0:DEPTH-1];

    // Port A Write Operation
    always @(posedge clk) begin
        if (we) begin
            ram[addr_a] <= din_a;
        end
    end

    // Port B Read Operation with registered output (essential to infer Block RAM)
    always @(posedge clk) begin
        dout_b <= ram[addr_b];
    end

endmodule

`endif

