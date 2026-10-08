"""KPI par entité de vérification.

Toutes les valeurs sont calculées à partir de la compilation slang et des violations :
pas d'estimation. Les comptages textuels (lignes, points de contrôle, waivers) se font
sur le source sans commentaires ni chaînes, branches `ifdef inactives comprises.
"""
import os
import re
from collections import Counter

from pyslang.ast import ExpressionKind, SymbolKind, VisitAction

from .core import class_chain, own_type_id, unwrap, walk
from . import gitstats
from .dut import analyze as analyze_dut, is_dut_file
from .textscan import extract_comments, find_markers, marker_regex, source_files, strip_comments

RE_WAIVER = re.compile(r"(?:uvm|chk)-waive:")

# KPI : (clé, libellé, unité, sens) — sens "low" = plus bas est meilleur
KPI_DEFS = [
    ("loc", "Lignes de code", "", None),
    ("classes", "Classes", "", None),
    ("check_points", "Points de contrôle actifs", "", None),
    ("errors", "Erreurs lint", "", "low"),
    ("warnings", "Warnings lint", "", "low"),
    ("errors_per_kloc", "Erreurs / kLOC", "", "low"),
    ("factory_pct", "Enregistrement factory", "%", "high"),
    ("msg_id_pct", "ID de messages conformes", "%", "high"),
    ("commented_checks", "Checks commentés", "", "low"),
    ("commented_checks_pct", "Part des checks commentés", "%", "low"),
    ("disabled_checks", "Désactivations de checks", "", "low"),
    ("wa_active", "Workarounds actifs", "", "low"),
    ("wa_dead", "Workarounds morts", "", "low"),
    ("waivers", "Waivers", "", "low"),
    ("markers", "Marqueurs TODO/FIXME/TBC…", "", "low"),
    ("baselined", "Dette (baseline)", "", "low"),
]

# inventaire de l'environnement : (clé, libellé)
INVENTORY_DEFS = [
    ("tests", "Tests"),
    ("sequences", "Séquences"),
    ("virtual_sequences", "dont séquences virtuelles"),
    ("items", "Sequence items"),
    ("envs", "Envs"),
    ("agents", "Agents"),
    ("drivers", "Drivers"),
    ("monitors", "Monitors"),
    ("sequencers", "Sequencers"),
    ("checkers", "Checkers"),
    ("coverage_collectors", "Collecteurs de couverture"),
    ("ral_blocks", "Blocs RAL"),
    ("ral_regs", "Registres RAL"),
    ("interfaces", "Interfaces"),
    ("constraints", "Contraintes"),
    ("covergroups", "Covergroups"),
    ("coverpoints", "Coverpoints"),
    ("crosses", "Crosses"),
    ("bins", "Bins déclarés"),
    ("illegal_ignore_bins", "Bins illegal/ignore"),
    ("cover_properties", "Cover properties"),
]
# KPI du DUT (RTL) : (clé, libellé)
DUT_DEFS = [
    ("modules", "Modules"),
    ("root_modules", "dont non instanciés (racines ou inactifs)"),
    ("interfaces_rtl", "Interfaces RTL"),
    ("instances", "Instances (élaboré)"),
    ("ports", "Ports"),
    ("port_bits", "Bits de ports"),
    ("parameters", "Paramètres"),
    ("always_ff", "Blocs séquentiels"),
    ("always_comb", "Blocs always_comb"),
    ("always_latch", "Blocs always_latch"),
    ("always_other", "Autres always"),
    ("fsm", "FSM (registres enum)"),
    ("flop_bits", "Bits de registres (élaboré)"),
    ("clocks", "Horloges (noms locaux)"),
    ("rtl_assertions", "Assertions dans le RTL"),
    ("slang_warnings", "Warnings slang"),
]
ROLE_KEY = {"test": "tests", "sequence": "sequences", "item": "items", "env": "envs",
            "agent": "agents", "driver": "drivers", "monitor": "monitors",
            "sequencer": "sequencers", "checker": "checkers", "coverage": "coverage_collectors"}
RE_COVER_PROP = re.compile(r"\bcover\s+(property|sequence)\b")
RE_INTERFACE = re.compile(r"^\s*interface\s+(?!class\b)(?:automatic\s+|static\s+)?(\w+)", re.M)


def _status(key, value, thresholds):
    """green / amber / red / None (KPI informatif ou valeur absente)."""
    t = thresholds.get(key)
    if t is None or value is None or isinstance(value, bool):
        return None
    if "red_above" in t and value > t["red_above"]:
        return "red"
    if "red_below" in t and value < t["red_below"]:
        return "red"
    if "amber_above" in t and value > t["amber_above"]:
        return "amber"
    if "amber_below" in t and value < t["amber_below"]:
        return "amber"
    return "green"


def compute(ctx, viols, baselined=(), entity_filter=None, churn_days=None, until=None):
    """Retourne {entité: {"kpi": {...}, "status": {...}, "overall": ..., "top_rules": [...]}}.

    Accumulation dans un Counter par entité avec des clés préfixées :
      cp:<type>  points de contrôle par type     mk:<marqueur>  marqueurs par type
      dut:<clé>  métriques DUT (dut.analyze)      autres         compteurs simples
    puis construction de k (valeurs), status (feux par seuil) et overall (pire feu).
    Ajouter un KPI : le compter ici, l'ajouter à KPI_DEFS / INVENTORY_DEFS / DUT_DEFS
    (libellé), éventuellement un seuil dans config.DEFAULTS["kpi"]["thresholds"], une colonne
    dans kpi_html, et une valeur attendue dans tests/run_tests.py (test_kpis ou test_dut)."""
    cfg = ctx.config
    thresholds = cfg["kpi"]["thresholds"]
    uvm = ctx.comp.getPackage("uvm_pkg")
    excl = [os.path.dirname(os.path.realpath(ctx.file_of(uvm.location)))] if uvm is not None else []

    ent = {}
    files_by_entity = {}
    re_checks = {k: re.compile(v) for k, v in cfg["kpi"]["check_points"].items()}
    re_markers = marker_regex(cfg["markers"], cfg["markers_case_sensitive"])

    def e(name):
        return ent.setdefault(name, Counter())

    # --- fichiers : lignes, points de contrôle, waivers ---
    for path in source_files(ctx.sm, cfg["exclude_paths"], excl):
        name = ctx.entity_of(path)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                src = f.read()
        except OSError:
            continue
        clean = strip_comments(src)
        c = e(name)
        c["files"] += 1
        files_by_entity.setdefault(name, []).append(path)
        if is_dut_file(path, cfg):
            c["dut_files"] += 1
        c["loc"] += sum(1 for ln in clean.splitlines() if ln.strip())
        for key, rx in re_checks.items():
            n = sum(1 for _ in rx.finditer(clean))
            c["cp:" + key] += n
            c["check_points"] += n
        c["cover_properties"] += len(RE_COVER_PROP.findall(clean))
        c["interfaces"] += len(RE_INTERFACE.findall(clean))
        for _, marker, _ in find_markers(src, re_markers):
            c["markers"] += 1
            c["mk:" + marker] += 1
        c["waivers"] += sum(1 for _, txt in extract_comments(src) if RE_WAIVER.search(txt))

    # --- classes : rôles, enregistrement factory, ID de messages ---
    fmt = re.compile(cfg["naming"]["message_id"])
    report_fns = {"uvm_report_error", "uvm_report_fatal"}

    def count_msg_ids(c, cls, methods):
        for m in methods:
            calls = []
            walk(m, lambda n: calls.append(n) if n.kind == ExpressionKind.Call
                 and not n.isSystemCall and n.subroutineName in report_fns else None)
            for call in calls:
                if not call.arguments:
                    continue
                c["msg_ids"] += 1
                arg = unwrap(call.arguments[0])
                if arg.kind == ExpressionKind.StringLiteral:
                    mid = str(arg.syntax).strip().strip('"') if arg.syntax else ""
                    ok = bool(fmt.match(mid))
                    if ok and cls is not None and ctx.is_checker(cls) and cfg["kpi"]["prefix_in_checkers"]:
                        ok = mid.startswith(cls.name.upper() + "_")
                    c["msg_ids_ok"] += ok

    for cls in ctx.classes:
        c = e(ctx.entity_of(ctx.file_of(cls.location)))
        c["classes"] += 1
        if not cls.isAbstract:
            role = ctx.role(cls)
            if role in ROLE_KEY:
                c[ROLE_KEY[role]] += 1
            if role == "sequence" and _is_virtual_sequence(ctx, cls):
                c["virtual_sequences"] += 1
            if ctx.derives(cls, {"uvm_reg_block"}):
                c["ral_blocks"] += 1
            elif ctx.derives(cls, {"uvm_reg"}):
                c["ral_regs"] += 1
            c["constraints"] += sum(1 for m in cls if m.kind == SymbolKind.ConstraintBlock
                                    and not ctx.is_macro_generated(m))
        registrable = not cls.isAbstract and (ctx.is_component(cls) or (
            ctx.is_object(cls) and not ctx.derives(cls, {"uvm_report_catcher"})))
        if registrable:
            c["registrable"] += 1
            c["registered"] += own_type_id(cls) is not None
        count_msg_ids(c, cls, ctx.methods(cls))

    for p in ctx.packages:          # fonctions et tâches déclarées au niveau du package
        for m in p:
            if m.kind == SymbolKind.Subroutine and m.syntax is not None and not ctx.sm.isMacroLoc(m.location):
                count_msg_ids(e(ctx.entity_of(ctx.file_of(m.location))), None, [m])

    # --- couverture fonctionnelle : covergroups de classes, interfaces et modules ---
    seen = set()

    def cov(sym):
        if sym.kind not in (SymbolKind.CovergroupType, SymbolKind.Coverpoint,
                            SymbolKind.CoverCross, SymbolKind.CoverageBin):
            return VisitAction.Advance
        if sym.hierarchicalPath.startswith("uvm_pkg") or ctx.sm.isMacroLoc(sym.location):
            return VisitAction.Advance
        fname = ctx.file_of(sym.location)
        key = (fname, sym.location.offset, sym.kind)   # une déclaration, même instanciée N fois
        if key in seen or any(os.path.realpath(fname).startswith(d + os.sep) for d in excl):
            return VisitAction.Advance
        seen.add(key)
        c = e(ctx.entity_of(fname))
        if sym.kind == SymbolKind.CovergroupType:
            c["covergroups"] += 1
        elif sym.kind == SymbolKind.Coverpoint:
            c["coverpoints"] += 1
        elif sym.kind == SymbolKind.CoverCross:
            c["crosses"] += 1
        elif sym.binsKind == sym.BinKind.Bins:        # BinKind : Bins / IllegalBins / IgnoreBins
            c["bins"] += 1
        else:
            c["illegal_ignore_bins"] += 1
        return VisitAction.Advance

    ctx.comp.getRoot().visit(cov)

    # --- DUT : design élaboré ---
    dut_counts, warn_codes = analyze_dut(ctx, ctx.entity_of)
    for name, cnt in dut_counts.items():
        c = e(name)
        for key, v in cnt.items():
            c["dut:" + key] += v

    # --- évolution : activité git ---
    churn = gitstats.collect(files_by_entity, churn_days, until) if churn_days else {}

    # --- violations ---
    rules_by_entity = {}
    for v in viols:
        c = e(v.entity)
        c["errors" if v.severity == "error" else "warnings"] += 1
        if v.rule == "CHK-COMMENTED":
            c["commented_checks"] += 1
        elif v.rule.startswith("CHK-"):
            c["disabled_checks"] += 1
        rules_by_entity.setdefault(v.entity, Counter())[v.rule] += 1
    for v in baselined:
        e(v.entity)["baselined"] += 1

    # --- workarounds : rattachés à l'entité de leur définition ---
    for w in ctx.workarounds.values():
        where = [f for f, _, _ in w.defined if not f.startswith("<")] or \
                [x[0] for x in (w.tested + w.used)]
        if not where:
            continue
        c = e(ctx.entity_of(where[0]))
        c["wa_total"] += 1
        c["wa_active"] += w.active
        c["wa_dead"] += bool(w.defined) and not w.tested and not w.used

    # --- ratios et statuts ---
    out = {}
    for name in sorted(ent):
        if entity_filter is not None and not entity_filter(name):
            continue
        c = ent[name]
        k = {key: c.get(key, 0) for key, *_ in KPI_DEFS}
        k.update(files=c["files"], wa_total=c["wa_total"])
        k["inventory"] = {key: c.get(key, 0) for key, _ in INVENTORY_DEFS}
        k["check_points_by_kind"] = {key: c["cp:" + key] for key in re_checks}
        k["markers_by_kind"] = {key[3:]: n for key, n in sorted(c.items()) if key.startswith("mk:") and n}
        k["errors_per_kloc"] = round(1000 * c["errors"] / c["loc"], 2) if c["loc"] else None
        k["factory_pct"] = round(100 * c["registered"] / c["registrable"], 1) if c["registrable"] else None
        k["msg_id_pct"] = round(100 * c["msg_ids_ok"] / c["msg_ids"], 1) if c["msg_ids"] else None
        total_checks = c["check_points"] + c["commented_checks"]
        k["commented_checks_pct"] = round(100 * c["commented_checks"] / total_checks, 1) if total_checks else None
        k["kind"] = "dut" if c["files"] and c["dut_files"] == c["files"] else "dv"
        if k["kind"] == "dut" or any(key.startswith("dut:") for key in c):
            dk = {key: c["dut:" + key] for key, _ in DUT_DEFS}
            dk["port_bits"] = c["dut:port_bits_in"] + c["dut:port_bits_out"]
            dk["rtl_assertions"] = c["cp:assertions"]
            dk["warning_codes"] = (warn_codes.get(name) or Counter()).most_common(5)
            k["dut"] = dk
        k["git"] = churn.get(name)
        status = {key: _status(key, k[key], thresholds) for key, *_ in KPI_DEFS}
        if "dut" in k:
            status.update({"dut." + key: _status("dut." + key, k["dut"][key], thresholds)
                           for key, _ in DUT_DEFS})
        rank = {"red": 2, "amber": 1, "green": 0}
        worst = max((s for s in status.values() if s), key=lambda s: rank[s], default=None)
        out[name] = {"kpi": k, "status": status, "overall": worst,
                     "top_rules": (rules_by_entity.get(name) or Counter()).most_common(5)}
    return out


def _is_virtual_sequence(ctx, cls):
    """Séquence virtuelle : ne pilote pas d'item concret (REQ = uvm_sequence_item),
    ou nommée *vseq* selon la convention courante."""
    if re.search(r"vseq|virtual", cls.name, re.I):
        return True
    for b in [cls, *class_chain(cls)]:
        if b.name == "uvm_sequence":
            req = next((m for m in b if m.name == "REQ"), None)
            if req is not None:
                t = getattr(req, "targetType", None)
                return t is not None and str(t.type).endswith("uvm_sequence_item")
    return False


def to_csv(kpis):
    """Une ligne par entité ; colonnes dynamiques pour les types de points de contrôle et de marqueurs."""
    keys = [key for key, *_ in KPI_DEFS] + ["files", "wa_total"]
    inv = [key for key, _ in INVENTORY_DEFS]
    cp_kinds = sorted({k for d in kpis.values() for k in d["kpi"]["check_points_by_kind"]})
    mk_kinds = sorted({k for d in kpis.values() for k in d["kpi"]["markers_by_kind"]})
    dut_keys = [key for key, _ in DUT_DEFS]
    git_keys = ["commits", "lines_added", "lines_deleted", "authors", "last_change", "days_since_change"]
    lines = [",".join(["entity", "kind", "overall"] + keys + inv + [f'"check_points:{k}"' for k in cp_kinds]
                      + [f'"markers:{k}"' for k in mk_kinds] + [f"dut:{k}" for k in dut_keys]
                      + [f"git:{k}" for k in git_keys])]
    for name, d in kpis.items():
        row = [f'"{name}"', d["kpi"]["kind"], d["overall"] or ""] + \
              ["" if d["kpi"][k] is None else str(d["kpi"][k]) for k in keys]
        row += [str(d["kpi"]["inventory"][k]) for k in inv]
        row += [str(d["kpi"]["check_points_by_kind"].get(k, 0)) for k in cp_kinds]
        row += [str(d["kpi"]["markers_by_kind"].get(k, 0)) for k in mk_kinds]
        dk = d["kpi"].get("dut") or {}
        row += [str(dk.get(k, "")) for k in dut_keys]
        g = d["kpi"].get("git") or {}
        row += ["" if g.get(k) is None else str(g.get(k)) for k in git_keys]
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"
