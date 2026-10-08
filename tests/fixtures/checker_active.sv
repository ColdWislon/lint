`include "uvm_macros.svh"
package chkact_pkg;
  import uvm_pkg::*;
  import checker_base_pkg::*;

  // ---------------- Checkers ----------------
  class my_sb extends checker_base;
    `uvm_component_utils(my_sb)
    bit enable = 1;                 // knob public : tentation pour les tests
    int exp_q[$];
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void write_act(int v);
      if (!enable) return;          // lecture interne : autorisée
      count_check(exp_q.pop_front() == v, "mismatch");
    endfunction
    virtual function int unsigned pending_items(); return exp_q.size(); endfunction
  endclass

  class lax_sb extends my_sb;       // variante permissive
    `uvm_component_utils(lax_sb)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
  endclass

  // ---------------- Env ----------------
  class my_env extends uvm_env;
    `uvm_component_utils(my_env)
    my_sb sb;
    bit has_sb = 1;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      if (has_sb)
        sb = my_sb::type_id::create("sb", this);              // expect: CHK-COND-CREATE
    endfunction
  endclass

  // ---------------- Report catcher ----------------
  class demote_catcher extends uvm_report_catcher;           // expect: CHK-REPORT-CATCHER
    function new(string name = "demote_catcher"); super.new(name); endfunction
    function action_e catch();
      if (get_severity() == UVM_ERROR) set_severity(UVM_INFO);
      return THROW;
    endfunction
  endclass

  // ---------------- Tests ----------------
  class base_test extends uvm_test;
    `uvm_component_utils(base_test)
    my_env env;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      env = my_env::type_id::create("env", this);
    endfunction
  endclass

  class clean_test extends base_test;                         // aucune violation
    `uvm_component_utils(clean_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void end_of_elaboration_phase(uvm_phase phase);
      env.set_report_id_action_hier("MY_INFO", UVM_DISPLAY);  // autorisé
    endfunction
  endclass

  class cheat_test extends base_test;
    `uvm_component_utils(cheat_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      my_sb::type_id::set_type_override(lax_sb::get_type());                // expect: CHK-FACTORY-OVERRIDE
      uvm_config_db#(bit)::set(this, "env.sb", "enable", 0);               // expect: CHK-CFGDB-KNOB
      super.build_phase(phase);
    endfunction
    function void end_of_elaboration_phase(uvm_phase phase);
      env.sb.enable = 0;                                                    // expect: CHK-KNOB-WRITE
      env.sb.set_report_id_action("CHK_MISMATCH", UVM_NO_ACTION);           // expect: CHK-REPORT-ACTION
      env.sb.set_report_severity_override(UVM_ERROR, UVM_WARNING);          // expect: CHK-SEVERITY-OVERRIDE
      env.sb.set_report_severity_action(UVM_ERROR, UVM_DISPLAY);            // expect: CHK-REPORT-ACTION
    endfunction
    task run_phase(uvm_phase phase);
      $assertoff(0);                                                        // expect: CHK-ASSERT-CTRL
    endtask
  endclass

  class waived_test extends base_test;
    `uvm_component_utils(waived_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    task run_phase(uvm_phase phase);
      // chk-waive: CHK-ASSERT-CTRL  reset asynchrone volontaire, revu le 08/10
      $assertoff(0);
      #100 $asserton(0);
    endtask
  endclass
endpackage
