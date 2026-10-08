`include "uvm_macros.svh"
package arch_pkg;
  import uvm_pkg::*;

  int unsigned g_err_count;                                // expect: UVM-PKG-STATE
  parameter int MAX_LEN = 64;                              // paramètre : OK

  class stat_cfg extends uvm_object;
    `uvm_object_utils(stat_cfg)
    static int unsigned n_instances;                       // expect: UVM-STATIC-STATE
    static const int unsigned VERSION = 2;                 // constante : OK
    function new(string name = "stat_cfg"); super.new(name); endfunction
  endclass
endpackage

module tb_top;
  import uvm_pkg::*;
  logic irq;

  class irq_watch;                                         // classe déclarée dans un module
    task wait_irq();
      @(posedge tb_top.irq);                               // expect: UVM-HIER-REF
    endtask
  endclass
endmodule
