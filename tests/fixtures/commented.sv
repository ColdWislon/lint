`include "uvm_macros.svh"
package cmt_pkg;
  import uvm_pkg::*;
  import checker_base_pkg::*;

  class bus_item extends uvm_sequence_item;
    rand int data;
    `uvm_object_utils(bus_item)
    function new(string name = "bus_item"); super.new(name); endfunction
  endclass

  // Le scoreboard compare chaque bus_item reçu au modèle, via count_check(ok, msg).   (prose : OK)
  // En cas d'écart on lève un `uvm_error avec l'ID BUS_SB_MISMATCH.                  (prose : OK)
  class bus_sb extends checker_base;
    `uvm_component_utils(bus_sb)
    uvm_analysis_imp #(bus_item, bus_sb) imp;
    bus_item exp_q[$];
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void write(bus_item t);
      bus_item exp = exp_q.pop_front();
      // count_check(exp.data == t.data, "data");                           // expect: CHK-COMMENTED
      //if (!exp.compare(t))                                                // expect: CHK-COMMENTED
      //  `uvm_error("BUS_SB_MISMATCH", "écart")                            // expect: CHK-COMMENTED
      // uvm-waive: CHK-COMMENTED  désactivé le temps du fix RTL #1234, revu le 08/10
      // `uvm_fatal("BUS_SB_FATAL", "arrêt")
    endfunction
    virtual function int unsigned pending_items(); return exp_q.size(); endfunction
  endclass

  /*
  class old_sb extends bus_sb;                                            // expect: CHK-COMMENTED
  endclass
  */

  class bus_env extends uvm_env;
    `uvm_component_utils(bus_env)
    bus_sb sb;
    uvm_analysis_port #(bus_item) ap;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      super.build_phase(phase);
      // sb = bus_sb::type_id::create("sb", this);                         // expect: CHK-COMMENTED
      ap = new("ap", this);
    endfunction
    function void connect_phase(uvm_phase phase);
      // ap.connect(sb.imp);                                                // expect: CHK-COMMENTED
      string s = "// `uvm_error(\"PAS_UN_COMMENTAIRE\", \"x\")";
    endfunction
  endclass
endpackage

module cmt_tb;
  logic clk, req, ack;
  // assert property (@(posedge clk) req |-> ##[1:3] ack);                 // expect: CHK-COMMENTED
  // TODO : écrire une assertion pour le protocole req/ack                  // expect: CMT-MARKER
  /* `DV_CHECK_EQ(req, ack) */                                             // expect: CHK-COMMENTED
endmodule
