# AGENTS.md — guide de reprise de uvm_lint

Ce fichier s'adresse à un agent (LLM) ou à un développeur qui reprend l'outil. Il décrit
l'architecture, les conventions à respecter, les pièges connus et la procédure pour faire
évoluer le code sans rien casser. Le `README.md` reste la documentation **utilisateur**
(options, règles, KPI) ; ce fichier est la documentation **mainteneur**.

À lire avant toute modification : la section « Invariants » et la section « Pièges pyslang ».

## 1. Ce que fait l'outil

`uvm_lint` analyse un environnement de vérification SystemVerilog/UVM (et le RTL du DUT) en
s'appuyant sur [slang](https://github.com/MikePopoloski/slang) via `pyslang` :

1. **Lint** : 37 règles sur le code UVM (factory, phases, objections, config_db, messages,
   nommage, indépendance tests/checkers, checkers toujours actifs, workarounds, commentaires).
2. **Tri par entité** : chaque violation est rattachée à une entité (package, dossier,
   module, ou table `[entities]`).
3. **KPI par entité** : DV (volume, points de contrôle, conformité, checks neutralisés,
   dette, inventaire tests/séquences/couverture) et DUT (modules, ports, bits de registres,
   FSM, warnings slang), activité git, historique et tendances, tableau de bord HTML.

Utilisateurs : une équipe DV (~20 ingénieurs) sur Cadence Xcelium, CI Jenkins. Le code est
commenté en **français** ; les messages et la sortie sont en français. Garder cette langue.

## 2. Démarrage rapide

```sh
pip install pyslang                      # testé avec pyslang 12.0.0, Python 3.11+ (tomllib)
git clone --depth 1 https://github.com/accellera-official/uvm-core.git /tmp/uvm
UVM_HOME=/tmp/uvm python3 tests/run_tests.py          # doit afficher « 11/11 fixtures OK »
python3 -m uvm_lint --list-rules
python3 -m uvm_lint +incdir+/tmp/uvm/src /tmp/uvm/src/uvm_pkg.sv \
    checker_base_pkg.sv tests/fixtures/checker_active.sv
```

**Règle d'or : lancer `tests/run_tests.py` avant et après chaque modification.** Il échoue sur
tout faux positif, faux négatif, règle sans fixture ou règle non documentée.

## 3. Carte du code

| Fichier | Rôle |
|---|---|
| `uvm_lint/cli.py` | Point d'entrée (`python3 -m uvm_lint`) : options, orchestration, entités, baseline, sorties texte/JSON, écriture des KPI |
| `uvm_lint/config.py` | `DEFAULTS` (toutes les clés de config, commentées) et chargement TOML fusionné |
| `uvm_lint/core.py` | Compilation slang (`compile_sources`), `Context` (classes, packages, classification UVM, entités, rapport, waivers), helpers AST |
| `uvm_lint/rules.py` | Les 37 règles, enregistrées par `@rule`, groupées par famille |
| `uvm_lint/textscan.py` | Scan textuel : suppression/extraction des commentaires, fichiers chargés, marqueurs |
| `uvm_lint/workarounds.py` | Inventaire des defines `WA_*` (défini / testé / utilisé / actif) |
| `uvm_lint/kpi.py` | Calcul des KPI par entité, feux, CSV ; définitions `KPI_DEFS`, `INVENTORY_DEFS`, `DUT_DEFS` |
| `uvm_lint/dut.py` | KPI du RTL sur le design élaboré (modules, ports, registres, FSM, warnings) |
| `uvm_lint/gitstats.py` | Activité git par entité sur une fenêtre de dates |
| `uvm_lint/kpi_html.py` | Tableau de bord HTML autonome (sections DV et DUT, deltas, tendances) |
| `checker_base_pkg.sv` | Classe SV de base des checkers (`CHK_DEAD`, `CHK_PENDING`) : complément dynamique des règles CHK-* |
| `tools/kpi_backfill.py` | Reconstruit l'historique des KPI en rejouant l'outil sur des commits passés |
| `tests/run_tests.py` | Runner de tests (fixtures annotées + tests unitaires entités/KPI/DUT/git + garde-fous doc) |
| `tests/fixtures/*.sv` | Une fixture par famille de règles, violations attendues en `// expect: RÈGLE` |
| `tests/entities/`, `tests/dut/` | Mini testbench à 3 entités et petit RTL vérifiés à la main |
| `uvm_lint.toml` | Exemple de configuration commenté, à garder synchronisé avec `config.DEFAULTS` |

## 4. Flux d'exécution (`cli.main`)

```
config.load(--config)
  -> core.compile_sources(args slang)         # CompileError -> code de sortie 2
  -> core.Context(comp, cfg)                  # classes/packages utilisateur, UVM exclu
  -> pour chaque règle non "off" (ou sélectionnée par --rules) : rule.fn(ctx)
       -> ctx.report(...) / ctx.report_at(...) # filtre --rules, sévérité, waiver
  -> dédoublonnage + entité (ctx.entity_of) + chemins relatifs
  -> --entity (filtre)  -> --write-baseline / --baseline
  -> KPI (kpi.compute -> dut.analyze, gitstats.collect) -> JSON / CSV / historique / HTML
  -> sortie texte groupée (format GCC) ou JSON
  -> code de sortie : 1 si erreur (ou warning avec --werror), sinon 0
```

## 5. Concepts

**Classification UVM** (`core.Context`) : par le **nom** des classes de base (`class_chain`).
- composant / objet / test / séquence : dérivation de `uvm_component`, `uvm_object`,
  `test_bases`, `uvm_sequence_base` ;
- **checker** : dérive d'une `checker_bases` (config), n'en est pas une, et n'est pas un
  collecteur de couverture ;
- **collecteur de couverture** : `uvm_subscriber` qui déclare un covergroup et ne dérive
  d'aucune autre base checker (sinon les coverage subscribers étaient pris pour des checkers) ;
- `ctx.role(cls)` donne le rôle pour le nommage et l'inventaire.

**Code utilisateur** : `ctx.classes` exclut `uvm_pkg`, `std`, `exclude_packages`,
`exclude_paths`. `ctx.methods(cls)` exclut les méthodes built-in et le code généré par les
macros (`uvm_*_utils`). Toujours passer par ces deux accès dans une règle.

**Entités** (`ctx.entity_of(fichier)`) dans cet ordre :
1. table `[entities]` (globs, première correspondance) ;
2. fichier DUT (`dut_paths`) : premier module déclaré (ou package) si
   `dut_entity_default = "module"`, sinon dossier parent ;
3. sinon package SV qui contient le fichier (fichiers `include compris), ou dossier parent.

**Violation** : `(file, line, rule, severity, message, entity)`, frozen. L'empreinte de
baseline exclut la ligne et l'entité : `file|rule|message`. La baseline compte les
occurrences : une occurrence de plus d'une violation connue est signalée.

**Sévérités** : défaut de la règle, surchargé par `[rules]`. `"off"` : la règle ne tourne que
si `--rules` la sélectionne explicitement (alors en warning). Utilisé pour `WA-ACTIVE` et
`CMT-MARKER`.

**Waivers** : `// uvm-waive: RÈGLE[, RÈGLE] justification` (ou `chk-waive:`) sur la ligne ou
la ligne précédente. Pas de waiver possible pour une violation « ligne de commande ».

**KPI** : `kpi.compute` accumule des `Counter` par entité (clés préfixées `cp:`, `mk:`,
`dut:`), puis construit pour chaque entité :
```json
{"kpi": {"kind": "dv|dut", "loc": 0, "...": 0, "inventory": {}, "check_points_by_kind": {},
         "markers_by_kind": {}, "dut": {} , "git": {} },
 "status": {"cle": "green|amber|red|null", "dut.cle": "..."},
 "overall": "pire feu", "top_rules": [["RÈGLE", n]]}
```
Un enregistrement d'historique = `{"date", "commit", "entities": {...}}`, une ligne JSONL par
run, fichier trié par date.

## 6. Invariants (ne pas casser)

1. **Les identifiants de règle sont stables.** Ils apparaissent dans les waivers et les
   baselines des utilisateurs. Renommer = migration explicite + mention dans le README.
2. **Format de sortie texte** `fichier:ligne: sévérité [RÈGLE] message` (lu par le parser GCC
   de Jenkins Warnings NG). Les en-têtes de groupe `=== ...` sont ignorés par ce parser.
3. **Schéma JSON** (`violations`, `entities`, `workarounds`) et clés des KPI : les historiques
   déjà enregistrés et les dashboards les relisent. Ajouter des clés, ne pas en renommer.
4. **Précision avant rappel** : une règle bruyante est désactivée par les équipes. Toute
   heuristique doit avoir des cas négatifs dans sa fixture. Mesurer sur du vrai code avant
   de livrer (voir § 9).
5. **Une règle = une docstring « Pourquoi / Détection / Limites / Fixture » + une fixture
   + une ligne dans le tableau des règles du README.** Le runner le vérifie.
6. **Une erreur de compilation arrête le lint** (code 2) : les règles supposent un design
   élaboré complet. Ne pas rendre les règles tolérantes à un AST partiel.
7. **Pas de dépendance hors stdlib + pyslang** (l'outil tourne sur les machines de CI).
8. **Config rétrocompatible** : toute nouvelle clé a un défaut dans `config.DEFAULTS` et un
   exemple commenté dans `uvm_lint.toml`.

## 7. Pièges pyslang (12.0.0) — tous vérifiés

Repérables dans le code par `grep -n "PIÈGE"`.

| Piège | Conséquence | Contournement (où) |
|---|---|---|
| L'API est en sous-modules : `pyslang.driver.Driver`, `pyslang.ast.SymbolKind`... | les exemples en ligne avec `pyslang.Driver` cassent | imports de `core.py` |
| `MethodFlags` / `VariableFlags` : `m.flags` lève `ValueError` sur une combinaison de bits | impossible de tester `BuiltIn`, `Const` | built-in : `m.syntax is None` ; const : texte source (`core.Context.methods`, règle UVM-STATIC-STATE) |
| `GenericClassDef.defaultSpecialization` est une propriété mal liée qui exige un Scope | `AttributeError`/`TypeError` | `type(s).defaultSpecialization.fget(s, s.parentScope)` (`Context.__post_init__`) |
| Conversions implicites et `void'(...)` : nœuds `Conversion` sans syntaxe | `str(node.syntax)` vide ou plante ; `void'(x.randomize())` non vu comme appel | `core.text()`, `core.unwrap()` |
| Les macros `` `uvm_error `` sont expansées | on ne voit pas la macro, on voit `uvm_report_error(...)` | `rules._message_ids` |
| Position d'un code issu de macro | `getFullyOriginalLoc` pointe dans `uvm_message_defines.svh` | `getFullyExpandedLoc` (`Context.file_of`, `report`) |
| `cls.find("type_id")` remonte l'héritage | une classe dérivée non enregistrée paraît enregistrée | itérer les membres propres (`core.own_type_id`) |
| Méthodes générées par `` `uvm_*_utils `` (create, get_type...) sont des membres normaux | faux positifs (UVM-NEW-DIRECT sur create()) | `ctx.methods()` exclut `isMacroLoc` |
| `Driver.reportMacros()` écrit sur le fd 1 en C++ | invisible pour `sys.stdout` | redirection du fd 1 (`core._final_macros`) |
| `Type.bitstreamWidth` est une propriété (int), pas une méthode ; `bitWidth` = 0 pour un tableau non packé | largeur de mémoire nulle | `dut._width` |
| Une assertion concurrente au niveau module est un `ProceduralBlock` « Always » | compté comme bloc always | `dut._is_assertion_block` |
| `str(diag.code)` = `"DiagCode(WidthTruncate)"` | pas d'accès direct au nom | regex dans `dut.analyze` |
| Une référence hiérarchique depuis un **package** est déjà une erreur slang | UVM-HIER-REF ne sert qu'aux classes déclarées dans des modules | docstring de la règle |
| `ast.Scope` n'a pas `asSymbol()` | impossible de remonter d'un sous-programme à sa classe | `subroutine.lexicalPath` + table `{lexicalPath: classe}` (`rules._referenced_classes`) |

Méthode quand un attribut pyslang surprend : sonder dans un script jetable
(`print([x for x in dir(obj) if not x.startswith("_")])`) sur un petit fichier SV, avant
d'écrire la règle. C'est comme ça que tous les pièges ci-dessus ont été trouvés.

## 8. Recettes

### Ajouter une règle
1. Écrire la fixture d'abord : `tests/fixtures/<famille>.sv` (ou une nouvelle), avec des cas
   positifs `// expect: MA-REGLE` **et** des cas négatifs plausibles (sans annotation).
   Une ligne `// args: +define+X` en tête passe des arguments slang à la fixture.
2. Ajouter la fonction dans `rules.py`, dans la section de sa famille :
   ```python
   @rule("UVM-MA-REGLE", "config", "warning", "Résumé d'une ligne (affiché par --list-rules)")
   def ma_regle(ctx):
       """Pourquoi : ...
       Détection : ...
       Limites : ...
       Fixture : config_messages.sv
       """
       for cls in ctx.classes:
           for c, m in calls(ctx, cls):          # (appel, méthode englobante)
               if c.subroutineName == "..." and "uvm_config_db" in sub_path(c):
                   ctx.report("UVM-MA-REGLE", c.sourceRange.start, "message actionnable")
   ```
   Helpers utiles : `calls`, `discarded_calls`, `sub_path`, `text`, `unwrap`, `lit`, `walk`,
   `own_type_id`, `class_chain`, `ctx.methods`, `ctx.is_*`, `ctx.role`, `ctx.report_at` (scan
   textuel avec `textscan`).
3. Ajouter la ligne dans le tableau des règles du `README.md`.
4. `UVM_HOME=... python3 tests/run_tests.py` : 0 faux positif, 0 faux négatif.
5. Mesurer sur du vrai code (§ 9) et lire chaque détection.

### Ajouter un KPI DV
Compter dans `kpi.compute` (fichier, classe ou AST), déclarer le libellé dans `KPI_DEFS`
(avec sens `low`/`high` s'il a un feu) ou `INVENTORY_DEFS` (informatif), seuil éventuel dans
`config.DEFAULTS["kpi"]["thresholds"]` + `uvm_lint.toml`, colonne/fiche dans `kpi_html.py`
(`DV_COLS`, `_dv_card`, `DV_TREND`, `DV_DELTA`), valeur attendue dans `test_kpis`.

### Ajouter un KPI DUT
Compter dans `dut.analyze_body` (par corps d'instance) ou `dut.analyze` (définitions,
diagnostics), le recopier dans la liste de clés « par définition » si nécessaire, libellé
dans `kpi.DUT_DEFS`, seuil `"dut.<clé>"`, affichage (`DUT_COLS`, `_dut_card`, `DUT_TREND`,
`DUT_DELTA`), valeur calculée à la main dans `test_dut` (commenter le calcul).

### Ajouter une option CLI
`cli.parse_args` (les arguments inconnus partent à slang : choisir un nom long en `--`
qui ne collisionne pas avec slang), README (tableau des options).

## 9. Validation sur du vrai code

Les règles ont été mesurées sur :
- la librairie DV lowRISC (OpenTitan/Ibex) : `vendor/lowrisc_ip/dv/sv` du dépôt
  `lowRISC/ibex` (58 classes) — 0 faux positif hors règles de convention (les ID
  `get_full_name()` de lowRISC sont un choix de leur part, signalé à juste titre) ;
  une vraie anomalie trouvée chez eux (message passé en ID de `` `uvm_fatal ``) ;
- les 206 fichiers DV d'Ibex pour CHK-COMMENTED : 2 détections, toutes vraies ;
- le RTL Ibex pour les KPI DUT, avec historique reconstruit sur 8 mois
  (`tools/kpi_backfill.py`) ; activité git recoupée avec `git log` directement.

Compiler lowRISC demande ses dépendances (`prim_util_pkg`, `prim_mubi_pkg`, `bus_params_pkg`,
`common_ifs_pkg`, `csr_utils`, `dv_base_reg`...) ; le RTL Ibex se compile avec `-y` sur
`prim/rtl` et `prim_generic/rtl`, `+define+SYNTHESIS`, `--top ibex_top`.

## 10. Décisions de conception et corrections passées

- **Règles retirées volontairement** : mauvaise macro d'enregistrement, constructeur à la
  mauvaise signature, objet sans nom par défaut. Slang et Xcelium les refusent déjà à la
  compilation (le code généré par les macros UVM ne compile pas). Ne pas les réintroduire.
- **INDEP-PKG-IMPORT** ne vise que les packages contenant des **tests** : un package d'agent
  contient normalement ses séquences et le checker l'importe pour le type d'item (faux
  positif corrigé). La référence directe à une séquence reste interdite (INDEP-CHECKER-TEST).
- **CHK-KNOB-WRITE** ignore `this.` / `super.` (faux positif sur `this.t = t` dans un
  collecteur de couverture).
- **Collecteurs de couverture** distingués des checkers (sinon soumis aux règles de checker).
- **CHK-COMMENTED / KPI** : une macro de check doit être suivie de `(` (faux positif lowRISC
  sur une phrase commençant par `` `DV_CHECK_FATAL ``).
- **Feux** : `_status` évalue rouge puis orange indépendamment ; un seuil orange seul ne
  s'allumait jamais dans une version antérieure (bug corrigé, couvert par `test_dut`).
- **UVM-CREATE-PHASE / UVM-CONNECT-PHASE** ne remontent pas le graphe d'appel : un helper
  appelé depuis build_phase n'est pas signalé (précision avant rappel).
- **Comptages textuels** (lignes, points de contrôle, marqueurs, cover properties) : voient
  aussi les branches `ifdef inactives. Choix assumé : l'inventaire ne dépend pas de la
  configuration compilée. Les comptages AST (classes, couverture, DUT) ne voient que le
  code compilé.
- **Commits** du tableau DUT : somme par entité (un commit sur deux blocs compte deux fois),
  indiqué sur la tuile.

## 11. Limites connues et pistes

- Classes paramétrées non spécialisées : seule la spécialisation par défaut est analysée.
- Règles d'équilibre (objections, start/finish_item) : comptage par méthode, sans flot.
- `config_db` avec clé construite dynamiquement : invisible (complément dynamique :
  `checker_base` lève `CHK_DEAD`).
- DUT : ports/FSM par première élaboration ; FSM reconnue seulement si l'état est un `enum` ;
  horloges = noms locaux, sans propagation entre modules ; modules non élaborés (paramètres
  qui les désactivent) : seules leurs lignes sont comptées.
- Pistes : lien couverture fonctionnelle ↔ modules RTL ; règles de reset (reset asynchrone
  manquant) ; propagation des domaines d'horloge (CDC) ; export SARIF.

## 12. Glossaire

| Terme | Sens ici |
|---|---|
| entité | regroupement de fichiers pour le tri et les KPI (package, dossier, module, ou `[entities]`) |
| checker | composant qui compare le comportement du DUT à une référence (scoreboard, predictor) |
| point de contrôle | check actif dans le code : `` `uvm_error ``, macro `*CHECK*`, `count_check`, assertion |
| workaround (WA) | define `WA_*` qui contourne un bug, à suivre jusqu'à sa suppression |
| marqueur | `TODO`, `FIXME`, `TBC`... dans un commentaire |
| baseline | violations existantes gelées, non signalées tant qu'elles ne réapparaissent pas en plus |
| waiver | exception justifiée dans le code, ligne par ligne |
| DUT | design sous test (RTL), fichiers de `dut_paths` |
