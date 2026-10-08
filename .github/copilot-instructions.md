# Instructions pour GitHub Copilot

Avant toute modification de uvm_lint, lire `AGENTS.md` à la racine : architecture, invariants
(identifiants de règle stables, format de sortie GCC, schéma JSON), pièges pyslang et
procédure d'ajout de règle ou de KPI.

En bref :
- code, commentaires et messages en français ;
- une règle = docstring « Pourquoi / Détection / Limites / Fixture » + fixture
  `tests/fixtures/*.sv` annotée `// expect: RÈGLE` + ligne dans le tableau du README ;
- `UVM_HOME=<uvm-core> python3 tests/run_tests.py` doit passer avant et après le changement ;
- précision avant rappel : une heuristique sans cas négatifs dans sa fixture n'est pas livrée ;
- dépendances : stdlib + pyslang uniquement.
