`include "uvm_macros.svh"
package naming_pkg;
  import uvm_pkg::*;
  import checker_base_pkg::*;

  class axi_wr_sb extends checker_base;                     // nom OK
    `uvm_component_utils(axi_wr_sb)
    int exp_q[$];
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void write(int v);
      if (exp_q.size() == 0)
        `uvm_error("AXI_WR_SB_UNEXPECTED", "transaction non attendue")   // OK
      else if (exp_q.pop_front() != v)
        `uvm_error("MISMATCH", "valeur différente")                      // expect: MSG-ID-PREFIX
      if (v < 0)
        `uvm_fatal("axi_wr_sb_neg", "valeur négative")                  // expect: MSG-ID-FORMAT
      if (v > 255)
        `uvm_error(get_type_name(), "hors plage")                       // expect: MSG-ID-LITERAL
      `uvm_info("dbg", "info non contrôlée", UVM_HIGH)                  // uvm_info : hors règle
    endfunction
    virtual function int unsigned pending_items(); return exp_q.size(); endfunction
  endclass

  class MyScoreboard extends uvm_scoreboard;                // expect: NAME-CLASS
    `uvm_component_utils(MyScoreboard)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
  endclass

  // uvm-waive: NAME-CLASS  IP legacy, renommage prévu au prochain refactoring
  class legacy_checker extends uvm_subscriber #(int);     // NAME-CLASS waivé
    `uvm_component_utils(legacy_checker)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void write(int t); endfunction
  endclass

  class axi_env extends uvm_env;                           // pas un checker : format seul
    `uvm_component_utils(axi_env)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void connect_phase(uvm_phase phase);
      `uvm_error("ENV_CFG_MISSING", "configuration absente")             // OK (pas de préfixe exigé)
      `uvm_error("Env cfg", "configuration absente")                     // expect: MSG-ID-FORMAT
    endfunction
  endclass
endpackage
