# uvm_lint

Linter UVM basé sur [slang](https://github.com/MikePopoloski/slang) (via `pyslang`).
slang élabore tout le testbench, UVM compris : les règles travaillent sur la sémantique
(hiérarchie de classes, types, appels résolus, macros expansées), pas sur du texte.

## Installation

```sh
pip install pyslang          # testé avec pyslang 12, Python ≥ 3.11
```

`uvm_lint/` est un package Python autonome : le copier dans le repo d'outils, ou ajouter
son dossier parent au `PYTHONPATH`.

## Utilisation

Mêmes arguments que xrun pour les sources : `-f`, `+incdir+`, `+define+`, fichiers.

```sh
python3 -m uvm_lint --config uvm_lint.toml \
    -f tb.f +incdir+$UVM_HOME/src $UVM_HOME/src/uvm_pkg.sv
```

| Option | Effet |
|---|---|
| `--config f.toml` | conventions, exclusions, sévérités (voir `uvm_lint.toml`) |
| `--rules 'CHK-*,MSG-*'` | n'exécuter que certaines règles (glob) |
| `--group-by entity\|file\|rule\|none` | regroupement de la sortie texte (défaut : `entity`) |
| `--entity 'axi*,dma_env'` | ne garder que ces entités (le code de sortie ne porte que sur elles) |
| `--format json` | sortie JSON : `violations` (avec leur `entity`), `entities` (compteurs), `workarounds` |
| `--write-baseline f.json` | geler les violations existantes |
| `--baseline f.json` | ne signaler que les violations nouvelles |
| `--werror` | les warnings font aussi échouer |
| `--list-rules` | liste des règles et sévérités effectives |
| `--workarounds` | inventaire des defines `WA_*` (voir plus bas) |
| `--kpi f.json` · `--kpi-csv f.csv` · `--kpi-html f.html` | KPI par entité (voir plus bas) |
| `--kpi-history f.jsonl` | ajoute le run à l'historique ; le HTML trace alors les tendances |
| `--kpi-git [JOURS]` | activité git par entité sur la fenêtre (défaut `churn_days` = 30) |
| `--kpi-date AAAA-MM-JJ` | date du run (reconstruction d'historique, voir `tools/kpi_backfill.py`) |

Codes de sortie : `0` propre, `1` violations (error, ou warning avec `--werror`),
`2` erreur de compilation ou d'usage. La sortie texte `fichier:ligne: sévérité [RÈGLE] message`
est lisible directement par le plugin Jenkins Warnings NG (parser GCC).

### Fichiers xrun

Les options spécifiques Cadence (`-access`, `-timescale`, `-uvmhome`...) ne sont pas comprises
par slang : générer une filelist dédiée ne contenant que sources, `+incdir+` et `+define+`.
Le code accepté par Xcelium mais non conforme à la norme sera signalé par slang comme erreur
de compilation : c'est un gain de portabilité, mais à traiter avant la mise en CI.

## Règles

| Famille | Règle | Défaut | Ce qui est vérifié |
|---|---|---|---|
| factory | UVM-REG-COMPONENT | error | composant non virtuel sans `` `uvm_component_utils `` |
| | UVM-REG-OBJECT | error | objet non virtuel (item, séquence, config) sans `` `uvm_object_utils `` |
| | UVM-NEW-DIRECT | error | classe enregistrée créée par `new()` au lieu de `type_id::create` |
| | UVM-CREATE-NAME | warning | `h = T::type_id::create("autre_nom")` |
| phases | UVM-CREATE-PHASE | error | composant créé dans une phase autre que `build_phase` |
| | UVM-CONNECT-PHASE | error | port connecté dans une phase autre que `connect_phase` |
| | UVM-SUPER-PHASE | error | phase redéfinie sans `super.<phase>()` alors que le parent utilisateur la définit |
| objections | UVM-OBJECTION-BALANCE | error | nombre de `raise_objection` ≠ `drop_objection` dans une méthode |
| | UVM-OBJECTION-LOCATION | warning | objection levée hors tests et séquences |
| | UVM-SEQ-ITEM-BALANCE | error | `start_item` sans `finish_item` |
| config | UVM-RANDOMIZE-CHECK | error | résultat de `randomize()` ignoré (y compris `void'(...)`) |
| | UVM-CFGDB-GET-CHECK | error | résultat de `uvm_config_db::get` ignoré |
| | UVM-CFGDB-WILDCARD | warning | `uvm_config_db::set` sur `"*"` |
| messages | UVM-NO-SV-SEVERITY | error | `$error`/`$fatal`/`$warning` dans une classe (non comptés par UVM) |
| | UVM-NO-DISPLAY | warning | `$display` dans une classe |
| | MSG-ID-LITERAL | error | ID de `` `uvm_error ``/`` `uvm_fatal `` non littéral |
| | MSG-ID-FORMAT | error | ID hors convention |
| | MSG-ID-PREFIX | error | dans un checker, ID ne commençant pas par `NOM_DE_CLASSE_` |
| nommage | NAME-CLASS | warning | nom de classe hors convention de son rôle (checker, test, agent...) |
| architecture | UVM-HIER-REF | error | référence hiérarchique depuis une classe |
| | UVM-PKG-STATE | warning | variable globale de package |
| | UVM-STATIC-STATE | warning | propriété `static` non `const` |
| indépendance | INDEP-CHECKER-TEST | error | checker qui référence un test, une séquence ou un type d'un package de tests |
| | INDEP-PKG-IMPORT | error | package de checkers qui importe un package contenant des tests (ou nommé comme tel) |
| checker actif | CHK-ASSERT-CTRL | error | `$assertoff`, `$assertkill`... hors checkers |
| | CHK-REPORT-ACTION | error | `UVM_NO_ACTION`, ou action d'erreur sans `UVM_COUNT` |
| | CHK-SEVERITY-OVERRIDE | error | rétrogradation de `UVM_ERROR`/`UVM_FATAL` |
| | CHK-REPORT-CATCHER | error | classe dérivée de `uvm_report_catcher` |
| | CHK-KNOB-WRITE | error | écriture d'un membre de checker depuis l'extérieur |
| | CHK-CFGDB-KNOB | error | `config_db::set` d'un champ type enable/check |
| | CHK-FACTORY-OVERRIDE | error | override factory d'un checker |
| | CHK-COND-CREATE | error | checker créé sous condition |
| | CHK-COMMENTED | warning | check laissé en commentaire : `` `uvm_error ``, assertion, `compare`, `count_check`, macro `*CHECK*`, création/connexion/classe de checker |
| commentaires | CMT-MARKER | off | liste chaque marqueur `TODO`/`FIXME`/`TBC`... avec sa ligne (`--rules CMT-MARKER`) |
| workarounds | WA-UNUSED | warning | define `WA_*` jamais testé ni utilisé (workaround mort) |
| | WA-UNDEFINED | warning | `WA_*` testé/utilisé mais défini nulle part dans la compilation |
| | WA-ACTIVE | off | chaque `WA_*` actif (à mettre en `error` pour une CI de release) |

Volontairement absentes, car déjà refusées à la compilation par slang et Xcelium via les macros
UVM : mauvaise macro d'enregistrement, constructeur à la mauvaise signature, objet sans
argument par défaut.

## Tri par entité

Chaque violation est rattachée à une entité de l'environnement de vérification :

1. la table `[entities]` de `uvm_lint.toml` (globs sur les chemins, première correspondance) ;
2. sinon le **package SV** qui contient le code, fichiers `` `include `` compris
   (`entity_default = "package"`), ou le dossier parent (`entity_default = "dir"`).

```toml
[entities]
"Agent AXI" = ["*/agents/axi/*"]
"Env DMA"   = ["*/env/dma/*", "*/tests/dma/*"]
```

La sortie texte est regroupée par entité, puis récapitulée :

```
=== bus_env_pkg — 1 erreur(s), 1 warning(s)
tb/env/bus_env_pkg.sv:11: error [MSG-ID-PREFIX] ...

Entité         Erreurs  Warnings  Règles les plus fréquentes
bus_test_pkg         2         1  NAME-CLASS (1), UVM-OBJECTION-BALANCE (1), CHK-ASSERT-CTRL (1)
bus_agent_pkg        1         1  UVM-NO-DISPLAY (1), UVM-REG-OBJECT (1)
```

Les lignes de violation gardent le format GCC : Warnings NG les lit toujours. Pour donner à
chaque responsable d'entité son propre verdict en CI : `--entity 'Agent AXI'`.

## KPI par entité

```sh
python3 -m uvm_lint --baseline uvm_lint_baseline.json \
    --kpi-html kpi.html --kpi-csv kpi.csv --kpi-history kpi_history.jsonl -f tb.f ...
```

| KPI | Définition | Feu par défaut |
|---|---|---|
| Lignes de code | lignes non vides hors commentaires, fichiers de l'entité | — |
| Classes, checkers, tests, séquences | classes compilées de l'entité, par rôle | — |
| Points de contrôle actifs | `` `uvm_error ``/`` `uvm_fatal ``, macros `` `*CHECK*( ``, `count_check(`, `assert`/`assume` hors commentaires (détail par type) | — |
| Erreurs, warnings lint | violations de l'entité (après baseline) | — |
| Erreurs / kLOC | erreurs × 1000 / lignes de code | orange > 0, rouge > 2 |
| Enregistrement factory | % des composants et objets non virtuels enregistrés | orange < 100 %, rouge < 90 % |
| ID de messages conformes | % des `` `uvm_error ``/`` `uvm_fatal `` à ID littéral, au format, préfixé dans les checkers | orange < 95 %, rouge < 80 % |
| Checks commentés | violations CHK-COMMENTED (et part sur actifs + commentés) | rouge > 0 |
| Désactivations de checks | autres violations CHK-* (`$assertoff`, catcher, knob...) | rouge > 0 |
| Workarounds actifs / morts | `WA_*` rattachés à l'entité de leur définition | orange > 0 |
| Waivers | commentaires `uvm-waive:` dans l'entité | — |
| Marqueurs | `TODO`, `FIXME`, `TBC`, `TBD`, `XXX`, `HACK`, `BUG`, `KLUDGE`, `WIP`, `À FAIRE` dans les commentaires, détail par marqueur | — (réglable : `markers = { amber_above = 20 }`) |
| Dette (baseline) | violations de l'entité absorbées par la baseline | orange > 0 |

En plus des KPI, un **inventaire** par entité (informatif, sans feu) :

| Élément | Comment il est compté |
|---|---|
| Tests, séquences (dont virtuelles), sequence items | classes non virtuelles par classe de base UVM ; séquence virtuelle = `uvm_sequence #(uvm_sequence_item)` ou nom en `*vseq*` |
| Envs, agents, drivers, monitors, sequencers, checkers | classes non virtuelles par classe de base |
| Collecteurs de couverture | `uvm_subscriber` déclarant un covergroup (non comptés comme checkers) |
| Blocs et registres RAL | dérivés de `uvm_reg_block` / `uvm_reg` |
| Covergroups, coverpoints, crosses, bins, bins illegal/ignore | déclarations élaborées par slang (une déclaration compte une fois, même instanciée N fois) |
| Contraintes | blocs `constraint` des classes |
| Cover properties, interfaces | texte hors commentaires |

Les covergroups d'interfaces et de modules ne sont comptés que s'ils sont élaborés : inclure le
`tb_top` qui instancie les interfaces dans la filelist du lint.

Le statut global d'une entité est son pire feu. Les seuils se règlent dans `[kpi.thresholds]`
(`red_above`/`amber_above` quand plus bas est meilleur, `red_below`/`amber_below` sinon), et ce
qui compte comme point de contrôle dans `[kpi.check_points]`.

Le tableau de bord HTML est autonome (aucune ressource externe, thème clair/sombre) : tuiles de
synthèse, tableau des entités triées par gravité, une fiche par entité avec ses règles les plus
fréquentes et, si un historique est fourni, les tendances (erreurs, warnings, checks commentés,
points de contrôle). Les données brutes sont embarquées dans la page (`#kpi-data`). La date et
`$GIT_COMMIT` (ou `$BUILD_TAG`) sont enregistrés à chaque run.

## KPI du DUT et évolution du RTL

Les fichiers qui correspondent à `dut_paths` (défaut `*/rtl/*`, `*/hdl/*`, `*/design/*`) forment
la section **DUT** du tableau de bord. Une entité DUT est par défaut le premier module déclaré
dans le fichier (`dut_entity_default = "module"`, ou `"dir"`) ; `[entities]` permet de regrouper
par bloc. Le RTL doit être dans la filelist : soit la filelist du testbench (qui l'inclut déjà
via `tb_top`), soit une filelist RTL seule (`--top <dut>`, `-y` pour les librairies).

| KPI DUT | Comptage | Feu par défaut |
|---|---|---|
| Modules (dont non instanciés), interfaces RTL | définitions des fichiers DUT | — |
| Instances | design élaboré | — |
| Ports, bits de ports, paramètres | par définition (première élaboration) | — |
| Blocs séquentiels / `always_comb` / `always_latch` / autres | par définition ; `always @(posedge ...)` compte comme séquentiel | latch : orange > 0 |
| Bits de registres | largeur des variables écrites dans les blocs séquentiels, **sommée sur toutes les instances** (paramètres effectifs) | — |
| FSM | registres de type `enum` | — |
| Horloges | noms distincts du premier front des blocs séquentiels (noms locaux, pas de propagation) | — |
| Assertions dans le RTL | `assert/assume/cover property` hors commentaires | — |
| Warnings slang | diagnostics slang sur les fichiers DUT, détail par code (`-Wextra`, `-Wunused`... pour en activer plus) | orange > 0, rouge > 20 |
| Marqueurs, workarounds, lignes | comme pour le DV | — |

**Activité git** (`--kpi-git`) : pour chaque entité, DV comme DUT, sur la fenêtre : commits,
lignes ajoutées et supprimées, auteurs, date du dernier changement. Le tableau DUT est trié
par activité. Le total des commits est une somme par entité (un commit qui touche deux blocs
compte deux fois).

**Évolution** : avec `--kpi-history`, chaque fiche affiche l'écart avec le run précédent
(modules, ports, bits de registres, warnings...) et les tendances. Pour ne pas attendre des
semaines de CI, `tools/kpi_backfill.py` reconstruit l'historique à partir de git : il extrait
un commit tous les N jours dans un worktree temporaire et y lance l'outil à la date du commit.

```sh
python3 tools/kpi_backfill.py --repo ../mon_projet --filelist lint_modele.f \
    --history kpi_history.jsonl --points 12 --every 14 -- --config uvm_lint.toml
```

La filelist modèle utilise `@ROOT@` pour la racine du dépôt ; une ligne préfixée par `?` n'est
gardée que si le fichier existe à ce commit (fichiers ajoutés en cours de projet), et `-y`
laisse slang trouver les modules quel que soit leur nombre.

## Workarounds (defines `WA_*`)

```sh
python3 -m uvm_lint --rules none --workarounds -f tb.f ...      # inventaire seul
python3 -m uvm_lint --workarounds --format json -f tb.f ...     # lint + inventaire en JSON
```

Pour chaque define préfixé `WA_` (préfixe configurable via `workaround_prefix`) :

- **défini** : `` `define `` dans les sources ou les includes, ou `+define+` en ligne de
  commande ou dans une filelist ;
- **testé** : `` `ifdef `` / `` `ifndef `` / `` `elsif `` ;
- **utilisé** : expansion `` `WA_X `` ;
- **`undef`** ;
- **état** : `actif` (défini à la fin du prétraitement de cette compilation, valeur
  affichée), `défini mais inactif` (dans une branche non compilée ou `undef`),
  `jamais défini`, ou `jamais testé ni utilisé`.

Le scan ignore commentaires et chaînes, et voit aussi les branches inactives : l'inventaire
liste tous les workarounds du code, quelle que soit la configuration compilée. L'état
« actif » dépend en revanche des `+define+` passés : lancer l'inventaire avec la filelist
de chaque configuration de régression.

```
  WA_FIFO_DEPTH = 4  [actif]
    défini    : tb/cfg_defines.svh:5
    testé     : 1×  tb/env/fifo_cfg.sv:17
    utilisé   : 1×  tb/env/fifo_cfg.sv:18
```

## Checks commentés (CHK-COMMENTED)

Scanne les commentaires `//` et `/* */` de tous les fichiers compilés (UVM exclu) et signale
le **code** de vérification mis en commentaire :

```
fifo_sb.sv:21: warning [CHK-COMMENTED] compare en commentaire : if (!exp.compare(t)) — réactiver ou supprimer
tb_top.sv:54: warning [CHK-COMMENTED] assertion en commentaire : assert property (@(posedge clk) req |-> ##[1:3] ack);
```

Pour ne pas signaler la documentation, le check doit être en tête de commentaire (éventuellement
après une affectation, un label, un `if (` ou l'objet appelant), ou la ligne doit finir par `;`.
« le scoreboard lève un `` `uvm_error `` en cas d'écart » n'est pas signalé.

Ce qui compte comme check est configurable (`commented_checks` dans `uvm_lint.toml`) ; les noms
des classes checkers sont ajoutés automatiquement. Un check désactivé volontairement se justifie
par un waiver sur la ligne précédente.

Mesuré sur 206 fichiers DV d'Ibex : 2 détections, toutes deux de vraies `assume property`
commentées.

## Waivers

Commentaire sur la ligne signalée ou la ligne précédente, avec une justification :

```systemverilog
// uvm-waive: CHK-ASSERT-CTRL  reset asynchrone volontaire, revu le 08/10
$assertoff(0);
```

Plusieurs règles : `// uvm-waive: RÈGLE1, RÈGLE2  justification`.
`chk-waive:` est accepté comme synonyme.

## Adoption sur une base existante

```sh
python3 -m uvm_lint --write-baseline uvm_lint_baseline.json -f tb.f ...   # une fois, commité
python3 -m uvm_lint --baseline uvm_lint_baseline.json -f tb.f ...         # en CI
```

La baseline est indépendante des numéros de ligne et compte les occurrences : une occurrence
supplémentaire d'une violation connue est signalée. On réduit la baseline au fil des corrections.

## checker_base_pkg.sv

Classe de base des checkers. Chaque comparaison passe par `count_check(ok, msg)` ; en
`check_phase` elle lève `CHK_DEAD` si moins de `min_checks` comparaisons ont été faites
(checker non connecté, aucun trafic) et `CHK_PENDING` s'il reste des éléments jamais comparés.
C'est le complément dynamique des règles CHK-* : une analyse statique ne voit pas un port
d'analyse non branché.

## Jenkins

```groovy
stage('UVM lint') {
  steps {
    sh 'python3 -m uvm_lint --config uvm_lint.toml --baseline uvm_lint_baseline.json -f lint.f > uvm_lint.log || true'
    recordIssues tools: [gcc(pattern: 'uvm_lint.log', id: 'uvm_lint', name: 'UVM lint')],
                 qualityGates: [[threshold: 1, type: 'TOTAL_ERROR', unstable: false]]
  }
}
stage('KPI vérification') {
  steps {
    copyArtifacts projectName: env.JOB_NAME, filter: 'kpi_history.jsonl', optional: true,
                  selector: lastSuccessful()
    sh 'python3 -m uvm_lint --kpi-html kpi.html --kpi-csv kpi.csv --kpi-history kpi_history.jsonl -f lint.f > /dev/null || true'
    archiveArtifacts 'kpi.html, kpi.csv, kpi_history.jsonl'
    publishHTML target: [reportDir: '.', reportFiles: 'kpi.html', reportName: 'KPI vérification']
  }
}
```

## Reprise et contribution

`AGENTS.md` est le guide mainteneur (architecture, invariants, pièges pyslang, recettes pour
ajouter une règle ou un KPI). `CLAUDE.md` et `.github/copilot-instructions.md` y renvoient pour
les assistants de code.

## Tests du linter

```sh
UVM_HOME=/chemin/uvm python3 tests/run_tests.py
```

Chaque fichier de `tests/fixtures/` annote les violations attendues (`// expect: RÈGLE`).
Le runner échoue sur tout faux positif, tout faux négatif, et toute règle sans test.
Toute nouvelle règle arrive avec sa fixture.

## Limites

- Analyse statique : `config_db` à clé construite dynamiquement, plusargs, overrides
  passés en ligne de commande échappent aux règles.
- Les classes paramétrées sont analysées dans leurs spécialisations existantes et leur
  spécialisation par défaut.
- Les règles d'équilibre (objections, `start_item`) comptent par méthode : un `raise` et un
  `drop` volontairement répartis dans deux méthodes demandent un waiver.
