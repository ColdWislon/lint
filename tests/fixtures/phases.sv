`include "uvm_macros.svh"
package phases_pkg;
  import uvm_pkg::*;

  class leaf_agent extends uvm_agent;
    `uvm_component_utils(leaf_agent)
    uvm_analysis_port #(int) ap;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      ap = new("ap", this);
    endfunction
  endclass

  class base_env extends uvm_env;
    `uvm_component_utils(base_env)
    leaf_agent a, b, late;
    uvm_tlm_analysis_fifo #(int) fifo;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      create_agents();                                    // helper appelé depuis build : OK
      fifo = new("fifo", this);
      a.ap.connect(fifo.analysis_export);                 // expect: UVM-CONNECT-PHASE
    endfunction
    function void create_agents();
      a = leaf_agent::type_id::create("a", this);
      b = leaf_agent::type_id::create("b", this);
    endfunction
    function void connect_phase(uvm_phase phase);
      b.ap.connect(fifo.analysis_export);                 // OK
      late = leaf_agent::type_id::create("late", this);   // expect: UVM-CREATE-PHASE
    endfunction
  endclass

  class derived_env extends base_env;
    `uvm_component_utils(derived_env)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);           // expect: UVM-SUPER-PHASE
      `uvm_info("DERIVED_ENV", "build sans super", UVM_LOW)
    endfunction
    function void connect_phase(uvm_phase phase);
      super.connect_phase(phase);                         // OK
    endfunction
  endclass
endpackage
