`include "uvm_macros.svh"
package mk_pkg;
  import uvm_pkg::*;
  // TODO: ajouter le mode burst                                    // expect: CMT-MARKER
  class mk_cfg extends uvm_object;
    `uvm_object_utils(mk_cfg)
    int unsigned depth = 8;   // FIXME valeur à confirmer avec le design // expect: CMT-MARKER
    /* TBC : timeout réel                                            // expect: CMT-MARKER
       TBD pour la v2 */                                              // expect: CMT-MARKER
    // Paramètres TBC/TBD selon la spec                                 // expect: CMT-MARKER, CMT-MARKER
    // À FAIRE : documenter                                            // expect: CMT-MARKER
    // pas de marqueur : todo en minuscules, TODOS, MTBC, XXXL, debug
    string s = "TODO dans une chaîne : ignoré";
    function new(string name = "mk_cfg"); super.new(name); endfunction
  endclass
endpackage
