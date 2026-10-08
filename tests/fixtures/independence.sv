`include "uvm_macros.svh"

package ind_agent_pkg;
  import uvm_pkg::*;
  class ind_item extends uvm_sequence_item;
    rand int addr;
    `uvm_object_utils(ind_item)
    function new(string name = "ind_item"); super.new(name); endfunction
  endclass
endpackage

package ind_test_pkg;
  import uvm_pkg::*;
  import ind_agent_pkg::*;
  class burst_seq extends uvm_sequence #(ind_item);
    `uvm_object_utils(burst_seq)
    int unsigned n_bursts = 8;
    function new(string name = "burst_seq"); super.new(name); endfunction
  endclass
  class smoke_test extends uvm_test;
    `uvm_component_utils(smoke_test)
    static int unsigned expected_writes = 8;              // expect: UVM-STATIC-STATE
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
  endclass
endpackage

package ind_env_pkg;
  import uvm_pkg::*;
  import checker_base_pkg::*;
  import ind_agent_pkg::*;
  import ind_test_pkg::*;                                 // expect: INDEP-PKG-IMPORT

  class wr_sb extends checker_base;
    `uvm_component_utils(wr_sb)
    uvm_analysis_imp #(ind_item, wr_sb) imp;              // item partagé : OK
    burst_seq ref_seq;                                    // expect: INDEP-CHECKER-TEST
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void write(ind_item t);
      count_check(t.addr < 1024, "adresse hors plage");
    endfunction
    function void check_phase(uvm_phase phase);
      super.check_phase(phase);
      if (m_n_checks != smoke_test::expected_writes)      // expect: INDEP-CHECKER-TEST
        `uvm_error("WR_SB_COUNT", "nombre d'écritures inattendu")
    endfunction
    virtual function int unsigned pending_items(); return 0; endfunction
  endclass
endpackage
