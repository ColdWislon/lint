`include "uvm_macros.svh"
package factory_pkg;
  import uvm_pkg::*;

  class good_item extends uvm_sequence_item;
    rand int a;
    `uvm_object_utils(good_item)
    function new(string name = "good_item"); super.new(name); endfunction
  endclass

  class unreg_item extends uvm_sequence_item;                          // expect: UVM-REG-OBJECT
    function new(string name = "unreg_item"); super.new(name); endfunction
  endclass

  virtual class abstract_cfg extends uvm_object;                       // virtuelle : pas de factory exigée
    function new(string name = "abstract_cfg"); super.new(name); endfunction
  endclass

  class unreg_drv extends uvm_driver #(good_item);                     // expect: UVM-REG-COMPONENT
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
  endclass

  class sub_drv extends uvm_driver #(good_item);
    `uvm_component_utils(sub_drv)
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
  endclass

  class good_env extends uvm_env;
    `uvm_component_utils(good_env)
    sub_drv    drv;
    uvm_analysis_port #(good_item) ap;
    function new(string name, uvm_component parent); super.new(name, parent); endfunction
    function void build_phase(uvm_phase phase);
      good_item it;
      super.build_phase(phase);
      drv = sub_drv::type_id::create("drv", this);
      ap  = new("ap", this);                                           // port TLM : new() normal
      it  = new("it");                                                 // expect: UVM-NEW-DIRECT
      it  = good_item::type_id::create("item");                        // expect: UVM-CREATE-NAME
    endfunction
  endclass
endpackage
