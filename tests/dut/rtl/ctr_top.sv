module ctr #(parameter int W = 8) (input logic clk, input logic rst_n, input logic en, output logic [W-1:0] q);
  typedef enum logic [1:0] {IDLE, RUN, DONE} st_e;
  st_e st, st_n;
  logic [3:0] tmp;
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) begin q <= '0; st <= IDLE; end
    else begin q <= q + 1; st <= st_n; end
  always_comb begin st_n = st; tmp = 4'd0; if (en) st_n = RUN; end
  assert property (@(posedge clk) disable iff (!rst_n) en |-> ##1 q != 0);
endmodule
module top (input logic clk, clk2, rst_n, input logic en, output logic [7:0] a, output logic [15:0] b, output logic x);
  ctr #(.W(8)) u0 (.clk, .rst_n, .en, .q(a));
  ctr #(.W(16)) u1 (.clk(clk2), .rst_n, .en, .q(b));
  always_ff @(posedge clk2) x <= en;
  generate for (genvar i = 0; i < 2; i++) begin : g end endgenerate
endmodule
