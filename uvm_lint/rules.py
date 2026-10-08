"""Jeu de règles UVM. Chaque règle est une fonction rule(ctx) enregistrée avec @rule.

Contrat d'une règle :
  - signature fn(ctx) ; parcourt ce dont elle a besoin (ctx.classes, ctx.methods(cls),
    ctx.packages, ctx.comp, fichiers sources) et appelle ctx.report(RULE_ID, location, msg)
    ou ctx.report_at(RULE_ID, fichier, ligne, msg) pour les scans textuels ;
  - ne filtre ni la sévérité, ni --rules, ni les waivers : ctx.report s'en charge ;
  - message en français, actionnable : ce qui est faux, pourquoi, quoi faire ;
  - docstring « Pourquoi / Détection / Limites / Fixture » : elle sert de référence aux
    mainteneurs et le runner de tests vérifie qu'elle existe ;
  - une fixture tests/fixtures/*.sv annote chaque violation attendue (// expect: RULE_ID),
    le runner échoue sur tout faux positif, faux négatif ou règle sans fixture.

L'ordre des règles dans ce fichier est l'ordre d'affichage de --list-rules (par famille).
"""
import fnmatch
import os
import re
from dataclasses import dataclass

from pyslang.ast import ExpressionKind, StatementKind, SymbolKind, VariableLifetime

from .core import class_chain, own_type_id, text, unwrap, walk


@dataclass
class Rule:
    """Métadonnées d'une règle. severity : défaut ("error", "warning", ou "off" = exécutée
    seulement si --rules la sélectionne explicitement)."""
    id: str
    family: str
    severity: str
    summary: str
    fn: object


RULES = {}


def rule(rule_id, family, severity, summary):
    """Décorateur d'enregistrement. rule_id : FAMILLE-NOM en majuscules, stable (il apparaît
    dans les waivers et les baselines des utilisateurs : ne jamais renommer sans migration)."""
    def deco(fn):
        RULES[rule_id] = Rule(rule_id, family, severity, summary, fn)
        return fn
    return deco


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
FUNCTION_PHASES = {"build_phase", "connect_phase", "end_of_elaboration_phase",
                   "start_of_simulation_phase", "extract_phase", "check_phase",
                   "report_phase", "final_phase"}


def calls(ctx, scope):
    """(appel, méthode englobante) pour toutes les méthodes utilisateur d'une classe."""
    for m in ctx.methods(scope):
        found = []
        walk(m, lambda n: found.append(n) if n.kind == ExpressionKind.Call else None)
        for c in found:
            yield c, m


def sub_path(call):
    """Chemin lexical de la méthode appelée, ex. "uvm_pkg::uvm_config_db::get" ("" pour un
    appel système). Sert à identifier les appels UVM sans dépendre des paramètres de classe."""
    sub = call.subroutine
    return "" if call.isSystemCall or sub is None else sub.lexicalPath


def discarded_calls(m):
    """Appels dont la valeur de retour est ignorée (statement seul ou void'(...))."""
    out = []

    def fn(n):
        if n.kind == StatementKind.ExpressionStatement:
            e = unwrap(n.expr)
            if e.kind == ExpressionKind.Call:
                out.append(e)
    walk(m, fn)
    return out


def lit(s):
    """Contenu d'un littéral chaîne "..." (texte source), sinon None."""
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else None


# ---------------------------------------------------------------------------
# Factory et construction
# ---------------------------------------------------------------------------
@rule("UVM-REG-COMPONENT", "factory", "error",
      "Tout uvm_component non virtuel est enregistré avec `uvm_component_utils")
def reg_component(ctx):
    """Pourquoi : un composant non enregistré ne peut pas être remplacé par override factory
    ni créé par type_id::create.
    Détection : pas de typedef `type_id` déclaré dans la classe elle-même (pas hérité).
    Les classes `virtual` sont ignorées (pas instanciables).
    Non traité ici : la mauvaise macro (`uvm_object_utils sur un composant) est déjà une erreur
    de compilation slang/Xcelium via le code généré par la macro.
    Fixture : factory.sv
    """
    for cls in ctx.classes:
        if cls.isAbstract or not ctx.is_component(cls):
            continue
        # une mauvaise macro (`uvm_object_utils sur un composant) est déjà une erreur de compilation
        if own_type_id(cls) is None:
            ctx.report("UVM-REG-COMPONENT", cls.location,
                       f"'{cls.name}' n'est pas enregistré dans la factory (`uvm_component_utils manquant)")


@rule("UVM-REG-OBJECT", "factory", "error",
      "Tout uvm_object non virtuel (item, séquence, config) est enregistré avec `uvm_object_utils")
def reg_object(ctx):
    """Pourquoi : idem UVM-REG-COMPONENT pour items, séquences, configs.
    Détection : uvm_object non composant, non virtuel, sans `type_id` propre.
    Exclusion : uvm_report_catcher (rarement enregistrés, déjà signalés par CHK-REPORT-CATCHER).
    Fixture : factory.sv
    """
    for cls in ctx.classes:
        if cls.isAbstract or not ctx.is_object(cls) or ctx.derives(cls, {"uvm_report_catcher"}):
            continue
        if own_type_id(cls) is None:
            ctx.report("UVM-REG-OBJECT", cls.location,
                       f"'{cls.name}' n'est pas enregistré dans la factory (`uvm_object_utils manquant)")


@rule("UVM-NEW-DIRECT", "factory", "error",
      "Les classes enregistrées sont créées par type_id::create, jamais par new()")
def new_direct(ctx):
    """Pourquoi : new() contourne la factory, les overrides des tests sont ignorés en silence.
    Détection : expression NewClass dont le type est une classe utilisateur enregistrée
    (a un `type_id`). `super.new(...)` est exclu par le texte source. Les ports TLM
    (uvm_analysis_port...) ne sont pas des classes utilisateur : new() reste normal pour eux.
    Le code généré par les macros (create() de `uvm_*_utils) est exclu via ctx.methods().
    Fixture : factory.sv
    """
    registered = {c.name for c in ctx.classes if own_type_id(c) is not None}
    for cls in ctx.classes:
        for m in ctx.methods(cls):
            def fn(n):
                if n.kind != ExpressionKind.NewClass:
                    return
                if text(n).startswith("super."):
                    return
                t = n.type.canonicalType if n.type is not None else None
                if t is not None and t.isClass and t.name in registered:
                    ctx.report("UVM-NEW-DIRECT", n.sourceRange.start,
                               f"'{t.name}' créé par new() : contourne la factory "
                               f"→ {t.name}::type_id::create(...)")
            walk(m, fn)


@rule("UVM-CREATE-NAME", "factory", "warning",
      "Le nom passé à create() est celui du handle (h = T::type_id::create(\"h\", this))")
def create_name(ctx):
    """Pourquoi : le nom passé à create() définit le chemin hiérarchique utilisé par
    config_db et les logs ; un nom différent du handle rend les deux trompeurs.
    Détection : affectation `h = T::type_id::create("nom", ...)` avec un nom littéral ≠ handle
    (dernier identifiant du membre gauche). Noms construits ($sformatf) : non vérifiés.
    Fixture : factory.sv
    """
    for cls in ctx.classes:
        for m in ctx.methods(cls):
            def fn(n):
                if n.kind != ExpressionKind.Assignment:
                    return
                rhs = unwrap(n.right)
                if rhs.kind != ExpressionKind.Call or rhs.subroutineName != "create":
                    return
                if "registry" not in sub_path(rhs) or not rhs.arguments:
                    return
                name = lit(text(rhs.arguments[0]))
                handle = re.split(r"[.\s]", text(n.left))[-1]
                if name is not None and re.fullmatch(r"\w+", handle) and name != handle:
                    ctx.report("UVM-CREATE-NAME", n.sourceRange.start,
                               f"handle '{handle}' créé avec le nom \"{name}\" : "
                               f"les chemins config_db et les logs seront trompeurs")
            walk(m, fn)


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------
@rule("UVM-CREATE-PHASE", "phases", "error",
      "Les composants sont créés dans build_phase uniquement")
def create_phase(ctx):
    """Pourquoi : la hiérarchie doit être figée à la fin de build_phase.
    Détection : appel create() d'un uvm_component_registry dans une méthode *_phase autre
    que build_phase. Un helper appelé depuis build_phase (create_agents()) n'est pas signalé :
    on ne remonte pas le graphe d'appel, volontairement, pour éviter les faux positifs.
    Fixture : phases.sv
    """
    for cls in ctx.classes:
        for c, m in calls(ctx, cls):
            if c.subroutineName == "create" and "uvm_component_registry" in sub_path(c) \
                    and m.name.endswith("_phase") and m.name != "build_phase":
                ctx.report("UVM-CREATE-PHASE", c.sourceRange.start,
                           f"composant créé dans {m.name} : la hiérarchie doit être figée en build_phase")


@rule("UVM-CONNECT-PHASE", "phases", "error",
      "Les ports TLM sont connectés dans connect_phase uniquement")
def connect_phase(ctx):
    """Pourquoi : connecter un port hors connect_phase casse l'ordre d'élaboration.
    Détection : appel connect() résolu sur uvm_pkg::uvm_port_base dans une méthode *_phase
    autre que connect_phase. Même limite que UVM-CREATE-PHASE pour les helpers.
    Fixture : phases.sv
    """
    for cls in ctx.classes:
        for c, m in calls(ctx, cls):
            if c.subroutineName == "connect" and sub_path(c).startswith("uvm_pkg::uvm_port_base") \
                    and m.name.endswith("_phase") and m.name != "connect_phase":
                ctx.report("UVM-CONNECT-PHASE", c.sourceRange.start,
                           f"port connecté dans {m.name} au lieu de connect_phase")


@rule("UVM-SUPER-PHASE", "phases", "error",
      "Une phase redéfinie appelle super.<phase>() quand la classe parente utilisateur la définit")
def super_phase(ctx):
    """Pourquoi : oublier super.build_phase() perd la config du parent (field automation,
    sous-composants créés par la classe de base).
    Détection : phase fonction redéfinie alors qu'une classe parente *utilisateur* (non UVM)
    la définit, sans `super.<phase>(` dans le texte du corps. Les phases tâches (run_phase...)
    sont exclues : ne pas appeler le parent y est souvent volontaire.
    Fixture : phases.sv
    """
    for cls in ctx.classes:
        user_bases = [b for b in class_chain(cls) if not ctx.is_excluded(b)]
        for m in ctx.methods(cls):
            if m.name not in FUNCTION_PHASES:
                continue
            parent_defines = any(
                any(x.name == m.name and x.kind == SymbolKind.Subroutine and not ctx.is_macro_generated(x)
                    for x in b) for b in user_bases)
            if not parent_defines:
                continue
            body = str(m.syntax) if m.syntax is not None else ""
            if not re.search(rf"\bsuper\s*\.\s*{m.name}\s*\(", body):
                ctx.report("UVM-SUPER-PHASE", m.location,
                           f"'{cls.name}::{m.name}' n'appelle pas super.{m.name}() : "
                           f"le {m.name} de la classe parente est perdu")


# ---------------------------------------------------------------------------
# Objections et séquences
# ---------------------------------------------------------------------------
@rule("UVM-OBJECTION-BALANCE", "objections", "error",
      "Chaque méthode a autant de raise_objection que de drop_objection")
def objection_balance(ctx):
    """Pourquoi : raise sans drop = test qui ne finit jamais ; drop en trop = fin prématurée.
    Détection : comptage textuel par méthode des appels raise_objection / drop_objection.
    Limite : un raise et un drop volontairement répartis dans deux méthodes demandent un waiver.
    Fixture : objections.sv
    """
    for cls in ctx.classes:
        for m in ctx.methods(cls):
            found = []
            walk(m, lambda n: found.append(n.subroutineName)
                 if n.kind == ExpressionKind.Call and not n.isSystemCall else None)
            r, d = found.count("raise_objection"), found.count("drop_objection")
            if r != d:
                ctx.report("UVM-OBJECTION-BALANCE", m.location,
                           f"'{cls.name}::{m.name}' : {r} raise_objection pour {d} drop_objection "
                           f"(risque de test qui ne se termine jamais ou trop tôt)")


@rule("UVM-OBJECTION-LOCATION", "objections", "warning",
      "Les objections sont levées uniquement par les tests et les séquences")
def objection_location(ctx):
    """Pourquoi : des objections levées dans les drivers/monitors rendent la fin de test
    imprévisible. Méthodologie : seuls tests et séquences les lèvent.
    Détection : raise_objection dans une classe qui ne dérive pas de objection_allowed_bases.
    Warning par défaut : certaines équipes (lowRISC) l'autorisent dans les monitors.
    Fixture : objections.sv
    """
    allowed = set(ctx.config["objection_allowed_bases"])
    for cls in ctx.classes:
        if ctx.derives(cls, allowed) or cls.name in allowed:
            continue
        for c, m in calls(ctx, cls):
            if c.subroutineName == "raise_objection":
                ctx.report("UVM-OBJECTION-LOCATION", c.sourceRange.start,
                           f"objection levée dans '{cls.name}' : réservé aux tests et séquences "
                           f"(sinon fins de test imprévisibles)")


@rule("UVM-SEQ-ITEM-BALANCE", "objections", "error",
      "Chaque start_item a son finish_item dans la même méthode")
def seq_item_balance(ctx):
    """Pourquoi : start_item sans finish_item bloque le sequencer.
    Détection : comptage par méthode, comme UVM-OBJECTION-BALANCE.
    Fixture : objections.sv
    """
    for cls in ctx.classes:
        for m in ctx.methods(cls):
            found = []
            walk(m, lambda n: found.append(n.subroutineName)
                 if n.kind == ExpressionKind.Call and not n.isSystemCall else None)
            s, f = found.count("start_item"), found.count("finish_item")
            if s != f:
                ctx.report("UVM-SEQ-ITEM-BALANCE", m.location,
                           f"'{cls.name}::{m.name}' : {s} start_item pour {f} finish_item "
                           f"(le sequencer reste bloqué)")


# ---------------------------------------------------------------------------
# Randomisation et configuration
# ---------------------------------------------------------------------------
@rule("UVM-RANDOMIZE-CHECK", "config", "error",
      "Le résultat de randomize() est toujours vérifié")
def randomize_check(ctx):
    """Pourquoi : un échec de contraintes non vérifié laisse des valeurs par défaut
    et le test passe sans rien couvrir.
    Détection : appel randomize() dont la valeur est ignorée (ExpressionStatement), y compris
    `void'(...)` qui est une Conversion autour de l'appel (voir unwrap()).
    Fixture : config_messages.sv
    """
    for cls in ctx.classes:
        for m in ctx.methods(cls):
            for c in discarded_calls(m):
                if c.subroutineName == "randomize":
                    ctx.report("UVM-RANDOMIZE-CHECK", c.sourceRange.start,
                               f"résultat de '{text(c)}' ignoré : un échec de contraintes passe inaperçu "
                               f"→ if (!...randomize()) `uvm_fatal(...)")


@rule("UVM-CFGDB-GET-CHECK", "config", "error",
      "Le résultat de uvm_config_db::get est toujours vérifié")
def cfgdb_get_check(ctx):
    """Pourquoi : une config absente laisse un handle null (plantage plus loin, loin
    de la cause) ou une valeur par défaut silencieuse.
    Détection : uvm_config_db::get dont la valeur est ignorée, `void'` compris.
    Fixture : config_messages.sv
    """
    for cls in ctx.classes:
        for m in ctx.methods(cls):
            for c in discarded_calls(m):
                if c.subroutineName == "get" and "uvm_config_db" in sub_path(c):
                    field_name = text(c.arguments[2]) if len(c.arguments) > 2 else "?"
                    ctx.report("UVM-CFGDB-GET-CHECK", c.sourceRange.start,
                               f"uvm_config_db::get de {field_name} non vérifié : "
                               f"une config absente laisse un handle null ou une valeur par défaut")


@rule("UVM-CFGDB-WILDCARD", "config", "warning",
      "uvm_config_db::set ne cible pas \"*\" (portée globale)")
def cfgdb_wildcard(ctx):
    """Pourquoi : set sur "*" rend le champ visible par tous les composants.
    Détection : 2e argument littéral exactement "*". "env.*" n'est pas signalé.
    Fixture : config_messages.sv
    """
    for cls in ctx.classes:
        for c, _ in calls(ctx, cls):
            if c.subroutineName == "set" and "uvm_config_db" in sub_path(c) and len(c.arguments) > 1:
                if lit(text(c.arguments[1])) == "*":
                    ctx.report("UVM-CFGDB-WILDCARD", c.sourceRange.start,
                               f"uvm_config_db::set sur \"*\" : visible par tous les composants, "
                               f"cibler le chemin précis")


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
SV_SEVERITY = {"$error", "$fatal", "$warning", "$info"}
SV_DISPLAY = {"$display", "$write", "$monitor", "$strobe", "$displayh", "$displayb", "$displayo"}


@rule("UVM-NO-SV-SEVERITY", "messages", "error",
      "Pas de $error/$fatal/$warning dans les classes : invisibles pour le compteur UVM")
def no_sv_severity(ctx):
    """Pourquoi : $error/$fatal ne passent pas par le report server UVM : non comptés,
    le test peut finir PASSED.
    Détection : appels système $error/$fatal/$warning/$info dans une méthode de classe.
    Les assertions des modules/interfaces ne sont pas concernées (hors classes).
    Fixture : config_messages.sv
    """
    for cls in ctx.classes:
        for c, _ in calls(ctx, cls):
            if c.isSystemCall and c.subroutineName in SV_SEVERITY:
                ctx.report("UVM-NO-SV-SEVERITY", c.sourceRange.start,
                           f"{c.subroutineName} n'est pas compté par le report server UVM "
                           f"→ `uvm_{c.subroutineName[1:]}")


@rule("UVM-NO-DISPLAY", "messages", "warning",
      "Pas de $display dans les classes : utiliser `uvm_info (verbosité, ID, filtrage)")
def no_display(ctx):
    """Pourquoi : $display ne se filtre pas par verbosité ni par ID.
    Fixture : config_messages.sv
    """
    for cls in ctx.classes:
        for c, _ in calls(ctx, cls):
            if c.isSystemCall and c.subroutineName in SV_DISPLAY:
                ctx.report("UVM-NO-DISPLAY", c.sourceRange.start,
                           f"{c.subroutineName} dans une classe → `uvm_info")


REPORT_FN = {"uvm_info": "uvm_report_info", "uvm_warning": "uvm_report_warning",
             "uvm_error": "uvm_report_error", "uvm_fatal": "uvm_report_fatal"}


def _message_ids(ctx):
    """(classe, appel, macro, 1er argument) pour chaque `uvm_error/`uvm_fatal...
    PIÈGE : les macros sont expansées par slang ; on cherche donc les appels
    uvm_report_error/uvm_report_fatal, pas le texte de la macro."""
    fns = {REPORT_FN[m]: m for m in ctx.config["naming"]["message_macros"]}
    for cls in ctx.classes:
        for c, _ in calls(ctx, cls):
            if c.subroutineName in fns and c.arguments:
                yield cls, c, fns[c.subroutineName], unwrap(c.arguments[0])


@rule("MSG-ID-LITERAL", "messages", "error",
      "L'ID des `uvm_error/`uvm_fatal est une chaîne littérale")
def msg_id_literal(ctx):
    """Pourquoi : un ID dynamique (get_full_name(), variable) empêche filtrage, waivers,
    set_report_id_action et le triage de régression par ID.
    Détection : les macros `uvm_error/`uvm_fatal sont expansées par slang en appels
    uvm_report_error/uvm_report_fatal ; on teste le premier argument (après unwrap).
    Les macros maison qui appellent `uvm_error (ex. `DV_CHECK) sont donc aussi vues.
    Fixture : naming.sv
    """
    for cls, c, macro, arg in _message_ids(ctx):
        if arg.kind != ExpressionKind.StringLiteral:
            ctx.report("MSG-ID-LITERAL", c.sourceRange.start,
                       f"`{macro} : l'ID '{text(arg)}' n'est pas une chaîne littérale "
                       f"(filtrage, waivers et triage impossibles)")


@rule("MSG-ID-FORMAT", "messages", "error",
      "L'ID des messages respecte le format configuré (défaut : MAJUSCULES_SOULIGNÉS)")
def msg_id_format(ctx):
    """Pourquoi : convention d'ID homogène pour le triage (regex naming.message_id).
    Fixture : naming.sv
    """
    fmt = re.compile(ctx.config["naming"]["message_id"])
    for cls, c, macro, arg in _message_ids(ctx):
        if arg.kind == ExpressionKind.StringLiteral:
            mid = lit(text(arg))
            if mid is not None and not fmt.match(mid):
                ctx.report("MSG-ID-FORMAT", c.sourceRange.start,
                           f"`{macro} : ID \"{mid}\" ne respecte pas {fmt.pattern}")


@rule("MSG-ID-PREFIX", "messages", "error",
      "Dans un checker, l'ID commence par le nom de la classe en majuscules")
def msg_id_prefix(ctx):
    """Pourquoi : dans un log de régression, savoir quel checker a levé l'erreur.
    Détection : ID conforme au format mais ne commençant pas par NOMCLASSE_ en majuscules,
    dans une classe checker (les classes de base de checker sont exemptées).
    Fixture : naming.sv
    """
    fmt = re.compile(ctx.config["naming"]["message_id"])
    for cls, c, macro, arg in _message_ids(ctx):
        if not ctx.is_checker(cls) or arg.kind != ExpressionKind.StringLiteral:
            continue
        mid, prefix = lit(text(arg)), cls.name.upper() + "_"
        if mid is not None and fmt.match(mid) and not mid.startswith(prefix):
            ctx.report("MSG-ID-PREFIX", c.sourceRange.start,
                       f"`{macro} : ID \"{mid}\" levé par le checker '{cls.name}' "
                       f"doit commencer par {prefix}")


# ---------------------------------------------------------------------------
# Nommage
# ---------------------------------------------------------------------------
@rule("NAME-CLASS", "naming", "warning",
      "Les classes UVM suivent la convention de nommage de leur rôle (checker, test, agent...)")
def name_class(ctx):
    """Pourquoi : conventions de nommage par rôle (naming.classes).
    Détection : rôle déduit de la classe de base (ctx.role) ; classes virtuelles exemptées.
    Fixture : naming.sv
    """
    conv = ctx.config["naming"]["classes"]
    for cls in ctx.classes:
        role = ctx.role(cls)
        if role is None or role not in conv or cls.isAbstract:
            continue
        if not re.match(conv[role], cls.name):
            ctx.report("NAME-CLASS", cls.location,
                       f"{role} '{cls.name}' ne respecte pas la convention {conv[role]}")


# ---------------------------------------------------------------------------
# Architecture et indépendance
# ---------------------------------------------------------------------------
@rule("UVM-HIER-REF", "architecture", "error",
      "Pas de référence hiérarchique depuis une classe : passer par une virtual interface")
def hier_ref(ctx):
    """Pourquoi : une référence hiérarchique (top.dut.sig) lie la classe à un top précis.
    Détection : expression HierarchicalValue dans une méthode de classe. Note : depuis un
    package, slang refuse déjà la référence (erreur de compilation) ; la règle sert surtout
    aux classes déclarées dans des modules/programmes.
    Fixture : architecture.sv
    """
    for cls in ctx.classes:
        for m in ctx.methods(cls):
            def fn(n):
                if n.kind == ExpressionKind.HierarchicalValue:
                    ctx.report("UVM-HIER-REF", n.sourceRange.start,
                               f"référence hiérarchique '{text(n)}' : couple la classe à un top précis "
                               f"→ virtual interface")
            walk(m, fn)


@rule("UVM-PKG-STATE", "architecture", "warning",
      "Pas de variable globale de package : état partagé entre composants et tests")
def pkg_state(ctx):
    """Pourquoi : une variable de package est un état global partagé entre tests et
    composants, invisible dans la hiérarchie et non réinitialisé.
    Détection : symboles Variable au niveau d'un package utilisateur (pas les parameter).
    Fixture : architecture.sv
    """
    for p in ctx.packages:
        for s in p:
            if s.kind == SymbolKind.Variable and not ctx.sm.isMacroLoc(s.location):
                ctx.report("UVM-PKG-STATE", s.location,
                           f"variable globale '{p.name}::{s.name}' : état partagé caché "
                           f"→ objet de config passé par uvm_config_db")


@rule("UVM-STATIC-STATE", "architecture", "warning",
      "Pas de propriété static modifiable dans les classes UVM")
def static_state(ctx):
    """Pourquoi : une propriété static est partagée par toutes les instances.
    Détection : ClassProperty static non const (const testé sur le texte source, voir
    PIÈGE pyslang dans core.Context.methods). Code généré par macro exclu.
    Fixture : architecture.sv, independence.sv
    """
    for cls in ctx.classes:
        if not (ctx.is_component(cls) or ctx.is_object(cls)):
            continue
        for s in cls:
            if s.kind == SymbolKind.ClassProperty and s.lifetime == VariableLifetime.Static \
                    and not ctx.is_macro_generated(s) \
                    and not re.search(r"\bconst\b", ctx.source_line(s.location)):
                ctx.report("UVM-STATIC-STATE", s.location,
                           f"propriété static '{cls.name}::{s.name}' : partagée entre toutes les instances "
                           f"et persistante entre phases")


def _referenced_classes(ctx, cls):
    """Types classe référencés par une classe (propriétés, variables, expressions).

    Couvre aussi T::x (NamedValue d'un membre statique) et T::f() (appel statique), dont le
    type d'expression n'est pas T : on retrouve la classe propriétaire par son lexicalPath."""
    refs = []
    by_path = {c.lexicalPath: c for c in ctx.classes}

    def add(t, loc):
        t = getattr(t, "canonicalType", t)
        if t is not None and t.isClass:
            refs.append((t, loc))

    for s in cls:
        if s.kind == SymbolKind.ClassProperty and not ctx.is_macro_generated(s):
            add(s.type, s.location)
    for m in ctx.methods(cls):
        def fn(n):
            if n.kind in (SymbolKind.Variable, SymbolKind.FormalArgument):
                add(n.type, n.location)
            elif isinstance(n.kind, ExpressionKind) and n.kind in (
                    ExpressionKind.NamedValue, ExpressionKind.MemberAccess, ExpressionKind.Call,
                    ExpressionKind.NewClass, ExpressionKind.DataType, ExpressionKind.Conversion):
                if n.type is not None:
                    add(n.type, n.sourceRange.start)
                if n.kind == ExpressionKind.NamedValue:
                    # membre statique T::x : la classe propriétaire de x
                    owner = by_path.get(n.symbol.lexicalPath.rsplit("::", 1)[0])
                    if owner is not None:
                        add(owner, n.sourceRange.start)
                if n.kind == ExpressionKind.Call and not n.isSystemCall and n.subroutine is not None:
                    # appel statique T::f() : la classe propriétaire de f
                    owner = by_path.get(n.subroutine.lexicalPath.rsplit("::", 1)[0])
                    if owner is not None:
                        add(owner, n.sourceRange.start)
        walk(m, fn)
    return refs


@rule("INDEP-CHECKER-TEST", "independence", "error",
      "Un checker ne référence aucun test ni aucune séquence")
def indep_checker_test(ctx):
    """Pourquoi : un checker qui connaît le test ou la séquence valide ce qu'on lui dit
    au lieu de ce que fait le DUT (prédiction biaisée par le stimulus).
    Détection : types classes référencés par le checker (propriétés, variables, expressions,
    propriétaire d'un membre ou d'un appel statique T::x) qui sont des tests, des séquences, ou
    viennent d'un package correspondant à test_packages.
    Fixture : independence.sv
    """
    test_pkgs = ctx.config["test_packages"]
    for cls in ctx.classes:
        if not ctx.is_checker(cls):
            continue
        for t, loc in _referenced_classes(ctx, cls):
            if ctx.is_excluded(t):
                continue
            why = None
            if ctx.is_test(t):
                why = "un test"
            elif ctx.is_sequence(t):
                why = "une séquence"
            elif any(fnmatch.fnmatch(ctx.package_of(t), p) for p in test_pkgs):
                why = f"un type du package de tests {ctx.package_of(t)}"
            if why:
                ctx.report("INDEP-CHECKER-TEST", loc,
                           f"le checker '{cls.name}' dépend de {why} ('{t.name}') : "
                           f"il doit prédire à partir du DUT, pas du stimulus")


@rule("INDEP-PKG-IMPORT", "independence", "error",
      "Un package contenant des checkers n'importe pas de package de tests")
def indep_pkg_import(ctx):
    """Pourquoi : complément de INDEP-CHECKER-TEST au niveau des packages.
    Détection : import (wildcard ou explicite) d'un package qui contient un uvm_test ou
    correspond à test_packages, depuis un package qui contient un checker.
    Décision : un package d'agent contenant des séquences n'est PAS visé (organisation
    standard, le checker a besoin du type d'item). Faux positif corrigé, voir test_entities.
    Fixture : independence.sv
    """
    # seuls les tests comptent : un package d'agent contient normalement ses séquences de base,
    # et un checker doit pouvoir l'importer pour le type d'item (la référence directe à une
    # séquence reste interdite par INDEP-CHECKER-TEST)
    pkg_has_tests = {ctx.package_of(c) for c in ctx.classes if ctx.is_test(c)}
    test_pkgs = ctx.config["test_packages"]
    checker_pkgs = {ctx.package_of(c) for c in ctx.classes if ctx.is_checker(c)}
    for p in ctx.packages:
        if p.name not in checker_pkgs:
            continue
        for s in p:
            if s.kind in (SymbolKind.WildcardImport, SymbolKind.ExplicitImport):
                imp = s.packageName
                if imp in pkg_has_tests or any(fnmatch.fnmatch(imp, pat) for pat in test_pkgs):
                    ctx.report("INDEP-PKG-IMPORT", s.location,
                               f"le package de checkers '{p.name}' importe le package de tests '{imp}'")


# ---------------------------------------------------------------------------
# Checkers toujours actifs
# ---------------------------------------------------------------------------
ASSERT_CTRL = {"$assertoff", "$assertkill", "$assertcontrol", "$assertfailoff", "$assertvacuousoff"}
REPORT_ACTION = re.compile(r"^set_report_(severity_|id_|severity_id_)action(_hier)?$")
SEVERITY_OVR = re.compile(r"^set_report_severity(_id)?_override(_hier)?$")
FACTORY_OVR = re.compile(r"^set_(type|inst)_override(_by_(type|name))?$")
KNOB_FIELD = re.compile(r"enable|disable|check|chk|scoreboard|\bsb", re.I)


def _non_checkers(ctx):
    """Classes susceptibles de désactiver un checker : tout sauf les checkers et leurs bases."""
    return [c for c in ctx.classes if not ctx.is_checker(c)
            and c.name not in ctx.config["checker_bases"]]


@rule("CHK-ASSERT-CTRL", "checker-actif", "error", "Pas de $assertoff/$assertkill hors checkers")
def chk_assert_ctrl(ctx):
    """Pourquoi : $assertoff/$assertkill hors checkers désactive la vérification.
    Fixture : checker_active.sv
    """
    for cls in _non_checkers(ctx):
        for c, _ in calls(ctx, cls):
            if c.isSystemCall and c.subroutineName in ASSERT_CTRL:
                ctx.report("CHK-ASSERT-CTRL", c.sourceRange.start, f"{c.subroutineName} désactive des assertions")


@rule("CHK-REPORT-ACTION", "checker-actif", "error",
      "Pas d'action UVM_NO_ACTION, ni d'erreur sans UVM_COUNT")
def chk_report_action(ctx):
    """Pourquoi : UVM_NO_ACTION supprime des messages ; une action de UVM_ERROR sans
    UVM_COUNT fait passer le test malgré l'erreur.
    Détection : texte des arguments des appels set_report_*_action*.
    Fixture : checker_active.sv
    """
    for cls in _non_checkers(ctx):
        for c, _ in calls(ctx, cls):
            name = c.subroutineName
            if c.isSystemCall or not REPORT_ACTION.match(name):
                continue
            args = [text(a) for a in c.arguments]
            action = args[-1] if args else ""
            sev = args[0] if "severity" in name and args else ""
            if "UVM_NO_ACTION" in action:
                ctx.report("CHK-REPORT-ACTION", c.sourceRange.start,
                           f"{name}(..., UVM_NO_ACTION) supprime des messages")
            elif sev in ("UVM_ERROR", "UVM_FATAL") and "UVM_COUNT" not in action and "UVM_EXIT" not in action:
                ctx.report("CHK-REPORT-ACTION", c.sourceRange.start,
                           f"{name} : action de {sev} sans UVM_COUNT, l'erreur ne fera pas échouer le test")


@rule("CHK-SEVERITY-OVERRIDE", "checker-actif", "error", "Pas de rétrogradation de UVM_ERROR/UVM_FATAL")
def chk_severity_override(ctx):
    """Pourquoi : rétrograder UVM_ERROR en WARNING masque les échecs.
    Fixture : checker_active.sv
    """
    for cls in _non_checkers(ctx):
        for c, _ in calls(ctx, cls):
            if not c.isSystemCall and SEVERITY_OVR.match(c.subroutineName) and c.arguments:
                sev = text(c.arguments[0])
                if sev in ("UVM_ERROR", "UVM_FATAL"):
                    ctx.report("CHK-SEVERITY-OVERRIDE", c.sourceRange.start,
                               f"{c.subroutineName} rétrograde {sev}")


@rule("CHK-REPORT-CATCHER", "checker-actif", "error", "Pas de uvm_report_catcher (masquage d'erreurs)")
def chk_report_catcher(ctx):
    """Pourquoi : un report catcher peut transformer n'importe quelle erreur en info.
    Détection : toute classe dérivée de uvm_report_catcher. Les catchers légitimes se waivent.
    Fixture : checker_active.sv
    """
    for cls in ctx.classes:
        if ctx.derives(cls, {"uvm_report_catcher"}):
            ctx.report("CHK-REPORT-CATCHER", cls.location,
                       f"'{cls.name}' dérive de uvm_report_catcher : peut masquer les erreurs des checkers")


@rule("CHK-KNOB-WRITE", "checker-actif", "error", "Un checker ne se configure pas depuis l'extérieur")
def chk_knob_write(ctx):
    """Pourquoi : un test qui écrit dans un checker (env.sb.enable = 0) le désactive.
    Détection : affectation à un membre d'un objet de type checker, depuis une classe non
    checker. Les écritures via this./super. sont ignorées (faux positif corrigé sur les
    collecteurs de couverture : `this.t = t`).
    Fixture : checker_active.sv
    """
    for cls in _non_checkers(ctx):
        for m in ctx.methods(cls):
            def fn(n):
                if n.kind == ExpressionKind.Assignment:
                    lhs = n.left
                    if lhs.kind == ExpressionKind.MemberAccess and ctx.is_checker_type(lhs.value.type) \
                            and text(lhs.value) not in ("this", "super"):
                        ctx.report("CHK-KNOB-WRITE", n.sourceRange.start,
                                   f"écriture de '{text(lhs)}' depuis '{cls.name}'")
            walk(m, fn)


@rule("CHK-CFGDB-KNOB", "checker-actif", "error", "Pas de config_db::set d'un knob d'activation")
def chk_cfgdb_knob(ctx):
    """Pourquoi : désactivation d'un checker par config_db.
    Détection : nom de champ littéral correspondant à KNOB_FIELD (enable, check, chk, sb...).
    Limite : clés construites dynamiquement ou nommées autrement ; complément dynamique :
    CHK_DEAD de checker_base.
    Fixture : checker_active.sv
    """
    for cls in _non_checkers(ctx):
        for c, _ in calls(ctx, cls):
            if c.subroutineName == "set" and "uvm_config_db" in sub_path(c) and len(c.arguments) >= 3:
                fld = lit(text(c.arguments[2]))
                if fld is not None and KNOB_FIELD.search(fld):
                    ctx.report("CHK-CFGDB-KNOB", c.sourceRange.start,
                               f"uvm_config_db::set de \"{fld}\" : ressemble à un knob d'activation de checker")


@rule("CHK-FACTORY-OVERRIDE", "checker-actif", "error", "Pas d'override factory d'un checker")
def chk_factory_override(ctx):
    """Pourquoi : remplacer un checker par une sous-classe permissive.
    Détection : appel set_*_override* dont le texte cite un nom de classe checker.
    Fixture : checker_active.sv
    """
    checker_names = {c.name for c in ctx.classes if ctx.is_checker(c)} | set(ctx.config["checker_bases"])
    for cls in _non_checkers(ctx):
        for c, _ in calls(ctx, cls):
            if not c.isSystemCall and FACTORY_OVR.match(c.subroutineName):
                full = text(c)
                hit = sorted(n for n in checker_names if re.search(rf"\b{re.escape(n)}\b", full))
                if hit:
                    ctx.report("CHK-FACTORY-OVERRIDE", c.sourceRange.start,
                               f"override factory d'un checker ({', '.join(hit)})")


@rule("CHK-COND-CREATE", "checker-actif", "error", "Un checker est toujours instancié")
def chk_cond_create(ctx):
    """Pourquoi : un checker créé sous condition peut ne jamais exister.
    Détection : create() d'un type checker dont la position est à l'intérieur d'un
    if/case (comparaison des plages source).
    Fixture : checker_active.sv
    """
    for cls in _non_checkers(ctx):
        for m in ctx.methods(cls):
            ranges, creates = [], []

            def fn(n):
                if n.kind in (StatementKind.Conditional, StatementKind.Case):
                    r = n.sourceRange
                    ranges.append((r.start.buffer, r.start.offset, r.end.offset))
                elif n.kind == ExpressionKind.Call and n.subroutineName == "create" \
                        and ctx.is_checker_type(n.type):
                    creates.append(n)
            walk(m, fn)
            for c in creates:
                s = c.sourceRange.start
                if any(b == s.buffer and lo <= s.offset <= hi for b, lo, hi in ranges):
                    ctx.report("CHK-COND-CREATE", s,
                               f"checker '{c.type.canonicalType.name}' créé sous condition")


# ---------------------------------------------------------------------------
# Workarounds (defines WA_*)
# ---------------------------------------------------------------------------
@rule("WA-UNUSED", "workarounds", "warning",
      "Un workaround défini est testé (`ifdef) ou utilisé (`WA_X) quelque part")
def wa_unused(ctx):
    """Pourquoi : un define WA_* jamais testé ni utilisé est un workaround mort.
    Données : ctx.workarounds (scan textuel, voir workarounds.py).
    Fixture : workarounds.sv
    """
    for w in ctx.workarounds.values():
        if w.defined and not w.tested and not w.used:
            for f, line, _ in w.defined:
                ctx.report_at("WA-UNUSED", f, line,
                              f"workaround {w.name} défini mais jamais testé ni utilisé : "
                              f"workaround mort, à supprimer")


@rule("WA-UNDEFINED", "workarounds", "warning",
      "Un workaround testé ou utilisé est défini quelque part (sources ou ligne de commande)")
def wa_undefined(ctx):
    """Pourquoi : un WA_* testé mais jamais défini dans la compilation est du code mort
    ou dépend d'une autre filelist.
    Fixture : workarounds.sv
    """
    for w in ctx.workarounds.values():
        if not w.defined:
            f, line = (w.tested or w.used)[0][:2]
            n = len(w.tested) + len(w.used)
            ctx.report_at("WA-UNDEFINED", f, line,
                          f"workaround {w.name} testé/utilisé {n}× mais défini nulle part dans cette "
                          f"compilation : code mort, ou define fourni par une autre filelist")


@rule("WA-ACTIVE", "workarounds", "off",
      "Signale chaque workaround actif (à activer pour bloquer les workarounds en CI de release)")
def wa_active(ctx):
    """Désactivée par défaut ; à mettre en error pour une CI de release (aucun workaround
    actif toléré). Une règle "off" s'exécute si --rules la sélectionne explicitement.
    Fixture : workarounds.sv
    """
    for w in ctx.workarounds.values():
        if w.active and w.defined:
            f, line, _ = w.defined[0]
            ctx.report_at("WA-ACTIVE", f, line, f"workaround {w.name} actif dans cette compilation")


# ---------------------------------------------------------------------------
# Checks commentés
# ---------------------------------------------------------------------------
# préfixe « code » devant le check : rien, affectation, label, if (...), else, begin/end
_CODE_PREFIX = re.compile(
    r"^\s*(?:(?:[\w.\[\]]+\s*(?:=|<=)\s*)"     # affectation        ok = 
    r"|(?:\w+\s*:\s*)"                             # label               a_chk:
    r"|(?:if\s*\(.*\)\s*)"                        # if (...) complet
    r"|(?:(?:if|while)\s*\(\s*!?\s*)"             # condition ouverte   if (!
    r"|(?:else|begin|end|return)\s+)*"
    r"[!\w.\[\]()]*\s*$")                         # objet appelant      exp / env.sb


def _commented_patterns(ctx):
    """Motifs de « check » pour CHK-COMMENTED : config.commented_checks + classes checkers."""
    pats = [(label, re.compile(rx)) for label, rx in ctx.config["commented_checks"].items()]
    checkers = sorted({c.name for c in ctx.classes if ctx.is_checker(c)} | set(ctx.config["checker_bases"]))
    if checkers:
        alt = "|".join(map(re.escape, checkers))
        pats.append(("classe checker", re.compile(rf"\bclass\s+\w+\s+extends\s+(?:{alt})\b")))
        pats.append(("création de checker", re.compile(rf"\b(?:{alt})::type_id::create\b")))
    return pats


@rule("CHK-COMMENTED", "checker-actif", "warning",
      "Pas de check laissé en commentaire (`uvm_error, assert, compare, scoreboard...)")
def chk_commented(ctx):
    """Pourquoi : un check commenté est une vérification désactivée invisible.
    Détection : commentaires (textscan.extract_comments) contenant un motif de
    config.commented_checks ou une classe checker. Pour ne pas signaler la documentation, le
    motif doit être en tête de commentaire (après affectation, label, `if (`, objet appelant :
    _CODE_PREFIX) ou la ligne doit finir par `;`. Mesure : 2 détections sur 206 fichiers DV
    d'Ibex, toutes vraies ; un faux positif lowRISC (`DV_CHECK_FATAL en prose) corrigé en
    exigeant une parenthèse après les macros.
    Fixture : commented.sv
    """
    from .textscan import extract_comments, source_files
    uvm = ctx.comp.getPackage("uvm_pkg")
    excl = [os.path.dirname(os.path.realpath(ctx.file_of(uvm.location)))] if uvm is not None else []
    pats = _commented_patterns(ctx)
    for path in source_files(ctx.sm, ctx.config["exclude_paths"], excl):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                src = f.read()
        except OSError:
            continue
        for line, txt in extract_comments(src):
            txt = txt.split("//")[0]          # note en fin de ligne commentée
            for label, rx in pats:
                m = rx.search(txt)
                if m is None:
                    continue
                # du code commenté, pas une phrase qui mentionne un check
                if _CODE_PREFIX.match(txt[:m.start()]) or txt.rstrip().endswith(";"):
                    snippet = txt.strip()
                    snippet = snippet if len(snippet) <= 70 else snippet[:67] + "..."
                    ctx.report_at("CHK-COMMENTED", path, line,
                                  f"{label} en commentaire : {snippet} — réactiver ou supprimer")
                    break


# ---------------------------------------------------------------------------
# Marqueurs de travail en cours (TODO, FIXME, TBC...)
# ---------------------------------------------------------------------------
@rule("CMT-MARKER", "commentaires", "off",
      "Liste les commentaires TODO/FIXME/TBC/TBD... (désactivée par défaut : --rules CMT-MARKER)")
def cmt_marker(ctx):
    """Liste les marqueurs TODO/FIXME/TBC... (config.markers), mots entiers, dans les
    commentaires uniquement. Désactivée par défaut : le KPI « marqueurs » donne le compte,
    cette règle donne la liste avec --rules CMT-MARKER.
    Fixture : markers.sv
    """
    from .textscan import find_markers, marker_regex, source_files
    rx = marker_regex(ctx.config["markers"], ctx.config["markers_case_sensitive"])
    uvm = ctx.comp.getPackage("uvm_pkg")
    excl = [os.path.dirname(os.path.realpath(ctx.file_of(uvm.location)))] if uvm is not None else []
    for path in source_files(ctx.sm, ctx.config["exclude_paths"], excl):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                src = f.read()
        except OSError:
            continue
        for line, marker, txt in find_markers(src, rx):
            snippet = txt if len(txt) <= 80 else txt[:77] + "..."
            msg = snippet if snippet.upper().startswith(marker.upper()) else f"{marker} — {snippet}"
            ctx.report_at("CMT-MARKER", path, line, msg)
