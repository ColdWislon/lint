`include "uvm_macros.svh"
package objections_pkg;
  import uvm_pkg::*;

  class bus_item extends uvm_sequence_item;
    rand int data;
    `uvm_object_utils(bus_item)
    function new(string name = "bus_item"); super.new(name); endfunction
  endclass

  class good_seq extends uvm_sequence #(bus_item);
    `uvm_object_utils(good_seq)
    function new(string name = "good_seq"); super.new(name); endfunction
    task body();
      bus_item req = bus_item::type_id::create("req");
      start_item(req);
      if (!req.randomize()) `uvm_fatal("GOOD_SEQ_RAND", "échec")
      finish_item(req);
    endtask
  endclass

  class broken_seq extends uvm_sequence #(bus_item);
    `uvm_object_utils(broken_seq)
    function new(string name = "broken_seq"); super.new(name); endfunction
    task body();                                            // expect: UVM-SEQ-ITEM-BALANCE
      bus_item req = bus_item::type_id::create("req");
      start_item(req);
      if (!req.randomize()) `uvm_fatal("BROKEN_SEQ_RAND", "échec")
    endtask
  endclass

  class bus_drv extends uvm_driver #(bus_item);
    `uvm_component_utils(bus_drv)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    task run_phase(uvm_phase phase);
      phase.raise_objection(this);                          // expect: UVM-OBJECTION-LOCATION
      #10;
      phase.drop_objection(this);
    endtask
  endclass

  class unbalanced_test extends uvm_test;
    `uvm_component_utils(unbalanced_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    task run_phase(uvm_phase phase);                        // expect: UVM-OBJECTION-BALANCE
      phase.raise_objection(this);
      #100;
    endtask
  endclass

  class good_test extends uvm_test;
    `uvm_component_utils(good_test)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    task run_phase(uvm_phase phase);
      phase.raise_objection(this);
      #100;
      phase.drop_objection(this);
    endtask
  endclass
endpackage
