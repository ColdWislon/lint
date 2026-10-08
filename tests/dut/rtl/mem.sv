module mem (input logic clk, input logic we, input logic [1:0] a, input logic [7:0] d, output logic [7:0] q);
  logic [7:0] m [4];
  typedef struct packed { logic v; logic [2:0] id; } e_t;
  e_t e_q;
  always_ff @(posedge clk) begin if (we) m[a] <= d; q <= m[a]; e_q.v <= we; end
endmodule
module lat (input logic en, input logic [3:0] d, output logic [3:0] q);
  always_latch if (en) q <= d;   // TODO: remplacer par une bascule
endmodule
