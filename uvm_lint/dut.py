"""KPI du DUT (RTL) : taille et structure du design élaboré par slang.

Un fichier est « DUT » s'il correspond à l'un des globs `dut_paths` de la config.

Deux niveaux de comptage :
  - par définition (chaque module source compté une fois) : modules, ports, blocs always,
    FSM, paramètres, horloges ;
  - élaboré (chaque instance de la hiérarchie compte) : instances, bits de registres.
    C'est la taille réelle du design avec ses paramètres effectifs.
"""
import fnmatch
import os
import re
from collections import Counter

from pyslang.ast import (ArgumentDirection, DefinitionKind, ExpressionKind, ProceduralBlockKind,
                         StatementKind, SymbolKind, VisitAction)

RE_EDGE = re.compile(r"\b(?:posedge|negedge)\s+([A-Za-z_][\w.]*)")
RE_ASSERT = re.compile(r"\b(assert|assume|cover)\s+property\b")


def is_dut_file(path, cfg):
    """Vrai si le fichier correspond à dut_paths (chemin absolu ou relatif au cwd)."""
    real = os.path.realpath(path)
    rel = os.path.relpath(real)
    return any(fnmatch.fnmatch(real, g) or fnmatch.fnmatch(rel, g) for g in cfg["dut_paths"])


def _lhs_symbols(expr, out):
    """Variables racines écrites par une expression d'affectation."""
    k = expr.kind
    if k == ExpressionKind.NamedValue:
        out.append(expr.symbol)
    elif k in (ExpressionKind.ElementSelect, ExpressionKind.RangeSelect, ExpressionKind.MemberAccess):
        _lhs_symbols(expr.value, out)
    elif k == ExpressionKind.Concatenation:
        for op in expr.operands:
            _lhs_symbols(op, out)


def _width(sym):
    """Largeur totale en bits d'une variable, tableaux non packés compris.

    PIÈGE pyslang : bitWidth vaut 0 pour un tableau non packé ; bitstreamWidth est une
    PROPRIÉTÉ (int), pas une méthode malgré son nom C++."""
    t = sym.type
    try:
        w = t.bitWidth or t.bitstreamWidth       # tableaux non packés : largeur totale
    except Exception:
        w = 0
    return int(w or 0)


def _is_assertion_block(block):
    """PIÈGE pyslang : une assertion concurrente au niveau module apparaît comme un
    ProceduralBlock « Always » ; on l'exclut des comptages de blocs always."""
    body = block.body
    return body.kind in (StatementKind.ConcurrentAssertion, StatementKind.ImmediateAssertion)


def _is_sequential(block):
    """always_ff, ou always classique dont le contrôle temporel contient un front (posedge/negedge)."""
    if block.procedureKind == ProceduralBlockKind.AlwaysFF:
        return True
    if block.procedureKind == ProceduralBlockKind.Always and block.body.kind == StatementKind.Timed:
        return bool(RE_EDGE.search(str(block.body.timing.syntax or "")))
    return False


def _own_members(scope):
    """Membres d'un corps de module, générés compris, sans descendre dans les sous-instances."""
    """Membres d'un corps de module, générés compris, sans descendre dans les sous-instances."""
    for m in scope:
        if m.kind in (SymbolKind.GenerateBlock, SymbolKind.GenerateBlockArray):
            if m.kind == SymbolKind.GenerateBlock and getattr(m, "isUninstantiated", False):
                continue
            yield from _own_members(m)
        else:
            yield m


def analyze_body(body):
    """Métriques d'un corps d'instance."""
    r = Counter()
    clocks, fsm_vars, flop_vars = set(), set(), {}
    for m in _own_members(body):
        k = m.kind
        if k == SymbolKind.Port:
            r["ports"] += 1
            w = int(m.type.bitWidth or 0)
            r["port_bits_in" if m.direction == ArgumentDirection.In else "port_bits_out"] += w
        elif k == SymbolKind.Instance:
            r["child_instances"] += 1
        elif k == SymbolKind.Parameter and not m.isLocalParam:
            r["parameters"] += 1
        elif k == SymbolKind.ProceduralBlock:
            if _is_assertion_block(m):
                continue
            pk = m.procedureKind
            if pk == ProceduralBlockKind.AlwaysFF or _is_sequential(m):
                r["always_ff"] += 1
            elif pk == ProceduralBlockKind.AlwaysComb:
                r["always_comb"] += 1
            elif pk == ProceduralBlockKind.AlwaysLatch:
                r["always_latch"] += 1
            elif pk == ProceduralBlockKind.Always:
                r["always_other"] += 1
            if _is_sequential(m):
                if m.body.kind == StatementKind.Timed:
                    edges = RE_EDGE.findall(str(m.body.timing.syntax or ""))
                    if edges:
                        clocks.add(edges[0])          # premier front = horloge, les suivants = resets
                targets = []

                def fn(n):
                    if n.kind == ExpressionKind.Assignment:
                        _lhs_symbols(n.left, targets)
                    return VisitAction.Advance
                m.visit(fn)
                for s in targets:
                    if s.kind == SymbolKind.Variable or s.kind == SymbolKind.Net:
                        flop_vars[id(s)] = s
    for s in flop_vars.values():
        r["flop_bits"] += _width(s)
        if s.type.canonicalType.isEnum:
            fsm_vars.add(s.name)
    r["fsm"] = len(fsm_vars)
    return r, clocks


def analyze(ctx, entity_of):
    """{entité: Counter} des KPI DUT, plus {entité: Counter(code warning slang)}.

    Par définition (premier corps rencontré) : ports, blocs, FSM, paramètres, horloges.
    Élaboré (chaque instance) : instances, bits de registres."""
    cfg = ctx.config
    out, warn_codes = {}, {}
    sm = ctx.sm

    def e(name):
        return out.setdefault(name, Counter())

    def file_of(sym):
        return str(sm.getFileName(sm.getFullyExpandedLoc(sym.location)))

    # --- définitions ---
    for d in ctx.comp.getDefinitions():
        if d.kind != SymbolKind.Definition:
            continue
        f = file_of(d)
        if not is_dut_file(f, cfg):
            continue
        c = e(entity_of(f))
        if d.definitionKind == DefinitionKind.Module:
            c["modules"] += 1
            if d.instanceCount == 0:
                c["root_modules"] += 1
        elif d.definitionKind == DefinitionKind.Interface:
            c["interfaces_rtl"] += 1

    # --- hiérarchie élaborée ---
    seen_defs, clocks_by_entity = set(), {}

    def visit(sym):
        if sym.kind != SymbolKind.Instance:
            return VisitAction.Advance
        body = sym.body
        f = file_of(body.definition)
        if not is_dut_file(f, cfg):
            return VisitAction.Advance
        ent = entity_of(f)
        c = e(ent)
        c["instances"] += 1
        metrics, clocks = analyze_body(body)
        c["flop_bits"] += metrics["flop_bits"]
        if body.definition.name not in seen_defs:          # comptage par définition
            seen_defs.add(body.definition.name)
            for key in ("ports", "port_bits_in", "port_bits_out", "parameters", "always_ff",
                        "always_comb", "always_latch", "always_other", "fsm"):
                c[key] += metrics[key]
            clocks_by_entity.setdefault(ent, set()).update(clocks)
        return VisitAction.Advance

    ctx.comp.getRoot().visit(visit)
    for ent, clk in clocks_by_entity.items():
        e(ent)["clocks"] = len(clk)

    # --- warnings slang sur le RTL ---
    for diag in ctx.comp.getAllDiagnostics():
        if diag.isError():
            continue
        loc = diag.location
        try:
            f = str(sm.getFileName(sm.getFullyExpandedLoc(loc)))
        except Exception:
            continue
        if f and is_dut_file(f, cfg):
            ent = entity_of(f)
            e(ent)["slang_warnings"] += 1
            # PIÈGE pyslang : str(diag.code) vaut "DiagCode(WidthTruncate)" ; pas d'accès direct au nom
            code = re.sub(r"^DiagCode\((.*)\)$", r"\1", str(diag.code))
            warn_codes.setdefault(ent, Counter())[code] += 1

    return out, warn_codes
