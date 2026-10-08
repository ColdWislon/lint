// checker_base_pkg.sv — classe de base pour tous les checkers (scoreboards, predictors...)
//
// Garantit en fin de simulation qu'un checker a réellement travaillé :
//   - CHK_DEAD    : moins de min_checks comparaisons effectuées
//                   (checker non connecté, aucun trafic, désactivé...)
//   - CHK_PENDING : des éléments attendus n'ont jamais été comparés
//
// Usage dans un checker dérivé :
//   - appeler count_check(ok, msg) pour CHAQUE comparaison
//   - implémenter pending_items() (taille des files d'attente)
//
// min_checks ne doit pas être modifié depuis un test : la règle
// check_checker_disable.py le signale (CHK-KNOB-WRITE).

`include "uvm_macros.svh"

package checker_base_pkg;
  import uvm_pkg::*;
  virtual class checker_base extends uvm_scoreboard;

    // Nombre minimum de comparaisons attendues sur un test
    protected int unsigned min_checks = 1;

    protected int unsigned m_n_checks;
    protected int unsigned m_n_errors;

    function new(string name, uvm_component parent);
      super.new(name, parent);
    endfunction

    // À appeler pour chaque comparaison effectuée par le checker
    protected function void count_check(bit ok, string msg = "");
      m_n_checks++;
      if (!ok) begin
        m_n_errors++;
        `uvm_error("CHK_MISMATCH", msg)
      end
    endfunction

    // Nombre d'éléments encore en attente de comparaison
    pure virtual function int unsigned pending_items();

    virtual function void check_phase(uvm_phase phase);
      super.check_phase(phase);
      if (m_n_checks < min_checks)
        `uvm_error("CHK_DEAD", $sformatf(
          "%0d comparaison(s) effectuée(s), minimum attendu %0d : checker inactif ou non connecté",
          m_n_checks, min_checks))
      if (pending_items() != 0)
        `uvm_error("CHK_PENDING", $sformatf(
          "%0d élément(s) jamais comparé(s) en fin de test", pending_items()))
    endfunction

    virtual function void report_phase(uvm_phase phase);
      super.report_phase(phase);
      `uvm_info("CHK_SUMMARY", $sformatf("%0d comparaison(s), %0d erreur(s)",
                                         m_n_checks, m_n_errors), UVM_NONE)
    endfunction

  endclass
endpackage
