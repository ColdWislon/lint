// args: +define+WA_FROM_CMDLINE=2
`include "uvm_macros.svh"
`include "workarounds_inc.svh"

`define WA_FIFO_DEPTH 4        // expect: WA-ACTIVE
`define WA_DEAD                // expect: WA-ACTIVE, WA-UNUSED
`define WA_REVERTED
`undef WA_REVERTED
`ifdef NOT_SET
  `define WA_DISABLED_BRANCH
`endif

package wa_pkg;
  import uvm_pkg::*;
  class wa_cfg extends uvm_object;
    `uvm_object_utils(wa_cfg)
`ifdef WA_FIFO_DEPTH
    int unsigned depth = `WA_FIFO_DEPTH;
`else
    int unsigned depth = 8;
`endif
`ifndef WA_GHOST                // expect: WA-UNDEFINED
    bit strict = 1;
`endif
`ifdef WA_FROM_CMDLINE
    bit cmd = 1;
`elsif WA_FROM_INCLUDE
    bit inc = 1;
`endif
`ifdef WA_REVERTED
    bit reverted = 1;
`endif
`ifdef WA_DISABLED_BRANCH
    bit never = 1;
`endif
    // `ifdef WA_IN_COMMENT : ignoré
    string s = "`WA_IN_STRING";
    function new(string name = "wa_cfg"); super.new(name); endfunction
  endclass
endpackage
