`include "uvm_macros.svh"
package cfgmsg_pkg;
  import uvm_pkg::*;

  class pkt_item extends uvm_sequence_item;
    rand int len;
    `uvm_object_utils(pkt_item)
    function new(string name = "pkt_item"); super.new(name); endfunction
  endclass

  class pkt_mon extends uvm_monitor;
    `uvm_component_utils(pkt_mon)
    virtual interface pkt_if vif;
    int unsigned timeout;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      pkt_item it = pkt_item::type_id::create("it");
      super.build_phase(phase);
      uvm_config_db#(int unsigned)::get(this, "", "timeout", timeout);          // expect: UVM-CFGDB-GET-CHECK
      void'(uvm_config_db#(int unsigned)::get(this, "", "timeout", timeout));   // expect: UVM-CFGDB-GET-CHECK
      if (!uvm_config_db#(int unsigned)::get(this, "", "timeout", timeout))     // OK
        `uvm_fatal("PKT_MON_CFG", "timeout absent")
      it.randomize();                                                            // expect: UVM-RANDOMIZE-CHECK
      void'(it.randomize() with { len < 10; });                                  // expect: UVM-RANDOMIZE-CHECK
      if (!it.randomize()) `uvm_error("PKT_MON_RAND", "échec")                   // OK
      $display("timeout = %0d", timeout);                                        // expect: UVM-NO-DISPLAY
      if (timeout == 0) $error("timeout nul");                                   // expect: UVM-NO-SV-SEVERITY
    endfunction
  endclass

  class pkt_test extends uvm_test;
    `uvm_component_utils(pkt_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      uvm_config_db#(int unsigned)::set(this, "*", "timeout", 100);             // expect: UVM-CFGDB-WILDCARD
      uvm_config_db#(int unsigned)::set(this, "env.mon", "timeout", 100);       // OK
    endfunction
  endclass
endpackage

interface pkt_if; logic clk; endinterface
