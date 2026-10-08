`include "uvm_macros.svh"
package bus_test_pkg;
  import uvm_pkg::*;
  // TODO: ajouter un test de reset ; FIXME : timeout
  /* TBC avec l'équipe design */
  class smoke extends uvm_test;
    `uvm_component_utils(smoke)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      $assertoff(0);
    endtask
  endclass
endpackage
