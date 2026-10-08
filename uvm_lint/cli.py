"""Point d'entrée : python3 -m uvm_lint [options] <arguments slang>"""
import argparse
import fnmatch
import json
import os
import sys
import time
from collections import Counter

from . import config as config_mod
from .core import CompileError, Context, compile_sources
from .rules import RULES

USAGE = """python3 -m uvm_lint [options] <arguments slang : -f filelist, +incdir+, +define+, fichiers>

Exemple :
  python3 -m uvm_lint --config uvm_lint.toml -f tb.f +incdir+$UVM_HOME/src $UVM_HOME/src/uvm_pkg.sv

Codes de sortie : 0 propre, 1 violations de sévérité error (ou warning avec --werror),
                  2 erreur de compilation ou d'usage."""


def parse_args(argv):
    """Options de l'outil ; tout argument inconnu est transmis tel quel à slang."""
    ap = argparse.ArgumentParser(prog="uvm_lint", usage=USAGE, allow_abbrev=False)
    ap.add_argument("--config", help="fichier uvm_lint.toml")
    ap.add_argument("--rules", help="n'exécuter que ces règles (glob, séparées par des virgules)")
    ap.add_argument("--format", choices=["text", "json"], default="text")
    ap.add_argument("--baseline", help="ignorer les violations listées dans ce fichier")
    ap.add_argument("--write-baseline", help="écrire toutes les violations actuelles dans ce fichier")
    ap.add_argument("--werror", action="store_true", help="les warnings font aussi échouer")
    ap.add_argument("--list-rules", action="store_true", help="lister les règles et quitter")
    ap.add_argument("--group-by", choices=["entity", "file", "rule", "none"], default="entity",
                    help="regroupement de la sortie texte (défaut : entité)")
    ap.add_argument("--entity", help="ne garder que ces entités (glob, séparées par des virgules)")
    ap.add_argument("--kpi", metavar="FICHIER.json", help="écrire les KPI par entité (JSON)")
    ap.add_argument("--kpi-csv", metavar="FICHIER.csv", help="écrire les KPI par entité (CSV)")
    ap.add_argument("--kpi-html", metavar="FICHIER.html", help="écrire le tableau de bord KPI (HTML autonome)")
    ap.add_argument("--kpi-history", metavar="FICHIER.jsonl",
                    help="ajouter les KPI de ce run à l'historique (et tracer les tendances dans le HTML)")
    ap.add_argument("--kpi-date", metavar="AAAA-MM-JJ",
                    help="date du run dans l'historique (pour reconstruire l'historique à partir de git)")
    ap.add_argument("--kpi-git", nargs="?", type=int, const=-1, metavar="JOURS",
                    help="ajouter l'activité git par entité (fenêtre en jours, défaut : churn_days)")
    ap.add_argument("--workarounds", action="store_true",
                    help="afficher l'inventaire des workarounds (defines WA_*)")
    return ap.parse_known_args(argv)


def list_rules(cfg):
    """--list-rules : règles par famille avec la sévérité effective (config appliquée)."""
    family = None
    for r in RULES.values():
        if r.family != family:
            family = r.family
            print(f"\n[{family}]")
        sev = cfg["rules"].get(r.id, r.severity)
        print(f"  {r.id:<24} {sev:<8} {r.summary}")


def _line(v):
    """Format GCC « fichier:ligne: sévérité [RÈGLE] message » (lu par Warnings NG) : ne pas changer."""
    return f"{v.file}:{v.line}: {v.severity} [{v.rule}] {v.message}"


def _counts(vs):
    """(erreurs, warnings) d'une liste de violations."""
    e = sum(v.severity == "error" for v in vs)
    return e, len(vs) - e


def print_grouped(viols, group_by):
    """Violations regroupées ; les lignes restent au format GCC (Warnings NG)."""
    if group_by == "none" or not viols:
        for v in viols:
            print(_line(v))
        return
    key = {"entity": lambda v: v.entity, "file": lambda v: v.file, "rule": lambda v: v.rule}[group_by]
    groups = {}
    for v in viols:
        groups.setdefault(key(v), []).append(v)
    if group_by == "rule":
        for vs in groups.values():
            vs.sort(key=lambda v: (v.entity, v.file, v.line))
    for name in sorted(groups):
        vs = groups[name]
        e, w = _counts(vs)
        print(f"\n=== {name} — {e} erreur(s), {w} warning(s)")
        for v in vs:
            print(_line(v))
    if group_by == "entity" and len(groups) > 1:
        width = max(len(n) for n in groups)
        print(f"\n{'Entité':<{width}}  Erreurs  Warnings  Règles les plus fréquentes")
        for name, vs in sorted(groups.items(), key=lambda kv: (-_counts(kv[1])[0], -len(kv[1]), kv[0])):
            e, w = _counts(vs)
            top = ", ".join(f"{r} ({n})" for r, n in Counter(v.rule for v in vs).most_common(3))
            print(f"{name:<{width}}  {e:>7}  {w:>8}  {top}")


def write_kpis(opts, ctx, viols, baselined_list, entity_filter, slang_args):
    """Calcule les KPI et écrit JSON / CSV / historique / HTML.

    L'historique est un JSONL trié par date (un run --kpi-date rétroactif s'insère à sa place) ;
    le HTML ne reçoit que les runs jusqu'à celui-ci, pour que « run précédent » soit juste."""
    from datetime import datetime, timezone

    from . import kpi, kpi_html
    churn = None
    if opts.kpi_git is not None:
        churn = ctx.config["churn_days"] if opts.kpi_git == -1 else opts.kpi_git
    now = datetime.now(timezone.utc).astimezone()
    if opts.kpi_date:
        now = datetime.fromisoformat(opts.kpi_date).astimezone()
    kpis = kpi.compute(ctx, viols, baselined_list, entity_filter, churn_days=churn,
                       until=now.timestamp())
    commit = os.environ.get("GIT_COMMIT") or os.environ.get("BUILD_TAG")
    record = {"date": now.isoformat(timespec="seconds"), "commit": commit, "entities": kpis}
    if opts.kpi:
        with open(opts.kpi, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=1, ensure_ascii=False)
    if opts.kpi_csv:
        with open(opts.kpi_csv, "w", encoding="utf-8") as f:
            f.write(kpi.to_csv(kpis))
    history = []
    if opts.kpi_history:
        if os.path.exists(opts.kpi_history):
            with open(opts.kpi_history, encoding="utf-8") as f:
                history = [json.loads(line) for line in f if line.strip()]
        history.append(record)
        history.sort(key=lambda r: r["date"])          # un run rétroactif s'insère à sa date
        with open(opts.kpi_history, "w", encoding="utf-8") as f:
            for r in history:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if opts.kpi_html:
        sub = f"{now:%d/%m/%Y %H:%M}" + (f" · {commit}" if commit else "") + \
              (f" · historique : {len(history)} run(s)" if history else "")
        with open(opts.kpi_html, "w", encoding="utf-8") as f:
            upto = [r for r in history if r["date"] <= record["date"]]
            f.write(kpi_html.render(kpis, subtitle=sub, history=upto))
    print(f"uvm_lint : KPI de {len(kpis)} entité(s) écrits", file=sys.stderr)


def main(argv=None):
    """Ordre : config -> compilation -> règles -> entités -> filtre --entity -> baseline -> KPI -> sortie.

    Les KPI voient les violations APRÈS baseline (la dette baselinée est comptée à part).
    Codes de sortie : 0 propre, 1 violations error (ou warning avec --werror), 2 usage/compilation."""
    opts, slang_args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        cfg = config_mod.load(opts.config)
    except (OSError, ValueError) as e:
        print(f"uvm_lint: configuration invalide : {e}", file=sys.stderr)
        return 2
    unknown = set(cfg["rules"]) - set(RULES)
    if unknown:
        print(f"uvm_lint: règle(s) inconnue(s) dans la config : {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2
    if opts.list_rules:
        list_rules(cfg)
        return 0
    if not slang_args:
        print(USAGE, file=sys.stderr)
        return 2

    t0 = time.time()
    try:
        compiled = compile_sources(slang_args)
    except CompileError as e:
        print(e.report)
        print("uvm_lint: erreurs de compilation, lint non exécuté", file=sys.stderr)
        return 2

    selected = None
    if opts.rules:
        pats = [p.strip() for p in opts.rules.split(",")]
        selected = lambda rid: any(fnmatch.fnmatch(rid, p) for p in pats)  # noqa: E731

    ctx = Context(compiled.comp, cfg, compiled=compiled, rule_filter=selected,
                  severities={rid: cfg["rules"].get(rid, r.severity) for rid, r in RULES.items()})
    for r in RULES.values():
        if (selected is None or selected(r.id)) and ctx.severities[r.id] != "off":
            r.fn(ctx)
    # une règle "off" par défaut (WA-ACTIVE) s'exécute si elle est demandée explicitement
    if selected is not None:
        for r in RULES.values():
            if selected(r.id) and ctx.severities[r.id] == "off":
                ctx.severities[r.id] = "warning"
                r.fn(ctx)

    cwd = os.getcwd()
    viols = sorted({v.__class__(os.path.relpath(v.file, cwd) if os.path.isabs(v.file) else v.file,
                                v.line, v.rule, v.severity, v.message, ctx.entity_of(v.file))
                    for v in ctx.violations},
                   key=lambda v: (v.entity, v.file, v.line, v.rule))
    entity_filter = None
    if opts.entity:
        epats = [p.strip() for p in opts.entity.split(",")]
        entity_filter = lambda name: any(fnmatch.fnmatch(name, p) for p in epats)  # noqa: E731
        viols = [v for v in viols if entity_filter(v.entity)]

    if opts.write_baseline:
        counts = Counter(v.fingerprint() for v in viols)
        with open(opts.write_baseline, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(counts.items())), f, indent=1, ensure_ascii=False)
        print(f"baseline écrite : {len(viols)} violation(s) dans {opts.write_baseline}", file=sys.stderr)
        return 0

    baselined, baselined_list = 0, []
    if opts.baseline:
        with open(opts.baseline, encoding="utf-8") as f:
            budget = Counter(json.load(f))   # nombre d'occurrences tolérées par empreinte
        kept = []
        for v in viols:
            if budget[v.fingerprint()] > 0:
                budget[v.fingerprint()] -= 1
                baselined_list.append(v)
            else:
                kept.append(v)                # nouvelle violation, ou occurrence en plus
        baselined = len(viols) - len(kept)
        viols = kept

    n_err = sum(v.severity == "error" for v in viols)
    n_warn = len(viols) - n_err

    if opts.kpi or opts.kpi_csv or opts.kpi_html or opts.kpi_history or opts.kpi_git is not None:
        write_kpis(opts, ctx, viols, baselined_list, entity_filter, slang_args)
    if opts.format == "json":
        out = [v.__dict__ for v in viols]
        summary = {}
        for v in viols:
            s_ = summary.setdefault(v.entity, {"errors": 0, "warnings": 0})
            s_["errors" if v.severity == "error" else "warnings"] += 1
        out = {"violations": out, "entities": summary}
        if opts.workarounds:
            out["workarounds"] = [w.as_dict() for w in ctx.workarounds.values()]
        print(json.dumps(out, indent=1, ensure_ascii=False))
    else:
        print_grouped(viols, opts.group_by)
        if opts.workarounds:
            from .workarounds import format_text
            print(("\n" if viols else "") + format_text(ctx.workarounds, cfg["workaround_prefix"], cwd))
        extra = f", {baselined} dans la baseline" if baselined else ""
        print(f"uvm_lint : {n_err} erreur(s), {n_warn} warning(s){extra} — "
              f"{len(ctx.classes)} classes analysées en {time.time() - t0:.1f} s", file=sys.stderr)

    return 1 if n_err or (opts.werror and n_warn) else 0
