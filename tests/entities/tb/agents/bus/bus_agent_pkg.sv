`include "uvm_macros.svh"
package bus_agent_pkg;
  import uvm_pkg::*;
  `include "bus_item.svh"
  class bus_mon extends uvm_monitor;
    `uvm_component_utils(bus_mon)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    task run_phase(uvm_phase phase);
      $display("mon");
    endtask
  endclass
  class bus_cov extends uvm_subscriber #(bus_item);
    `uvm_component_utils(bus_cov)
    bus_item t;
    covergroup cg_bus;
      cp_a: coverpoint t.a { bins zero = {0}; bins pos = {[1:$]}; illegal_bins neg = {[$:-1]}; }
      cp_a2: coverpoint t.a[0];
      x_a: cross cp_a, cp_a2;
    endgroup
    function new(string name, uvm_component parent); super.new(name, parent); cg_bus = new(); endfunction
    function void write(bus_item t); this.t = t; cg_bus.sample(); endfunction
  endclass
  class bus_rd_seq extends uvm_sequence #(bus_item);
    `uvm_object_utils(bus_rd_seq)
    function new(string name = "bus_rd_seq"); super.new(name); endfunction
  endclass
endpackage
