`include "uvm_macros.svh"
package bus_env_pkg;
  import uvm_pkg::*;
  import checker_base_pkg::*;
  import bus_agent_pkg::*;
  class bus_sb extends checker_base;
    `uvm_component_utils(bus_sb)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void write(bus_item t);
      // count_check(t.a == 0, "a");
      `uvm_error("MISMATCH", "x")
    endfunction
    virtual function int unsigned pending_items(); return 0; endfunction
  endclass
endpackage
