#!/usr/bin/env python3
"""Tests de non-régression des règles.

Chaque fichier de tests/fixtures/ annote les violations attendues :
    <code>   // expect: RÈGLE[, RÈGLE...]
Le test échoue si une violation attendue manque (faux négatif) ou si une
violation non annotée apparaît (faux positif).

Usage : UVM_HOME=/chemin/uvm python3 tests/run_tests.py [fixture.sv ...]
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from uvm_lint import config as config_mod          # noqa: E402
from uvm_lint.core import CompileError, Context, compile_sources  # noqa: E402
from uvm_lint.rules import RULES                    # noqa: E402

EXPECT = re.compile(r"//\s*expect:\s*([A-Z0-9_\-, ]+)")


def expectations(path):
    """{(ligne, règle)} annotés par « // expect: RÈGLE[, RÈGLE] » dans une fixture."""
    exp = set()
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            m = EXPECT.search(line)
            if m:
                for r in re.split(r"[,\s]+", m.group(1).strip()):
                    if r:
                        exp.add((i, r))
    return exp


def extra_args(path):
    """Arguments slang propres à une fixture : ligne « // args: ... » en tête de fichier."""
    with open(path, encoding="utf-8") as f:
        first = f.readline()
    m = re.match(r"//\s*args:\s*(.*)", first)
    return m.group(1).split() if m else []


def run_fixture(path, uvm_src):
    """Compile une fixture avec UVM et checker_base_pkg, lance toutes les règles (y compris
    celles « off » par défaut) et renvoie les violations de ce fichier."""
    args = [f"+incdir+{uvm_src}", f"+incdir+{ROOT}", f"+incdir+{os.path.dirname(path)}",
            *extra_args(path), f"{uvm_src}/uvm_pkg.sv", f"{ROOT}/checker_base_pkg.sv", path]
    compiled = compile_sources(args)
    # en test, toutes les règles tournent, y compris celles "off" par défaut
    ctx = Context(compiled.comp, config_mod.load(), compiled=compiled,
                  severities={rid: "error" if r.severity == "off" else r.severity
                              for rid, r in RULES.items()})
    for r in RULES.values():
        r.fn(ctx)
    real = os.path.realpath(path)
    return {(v.line, v.rule) for v in ctx.violations if os.path.realpath(v.file) == real}, ctx


def test_entities(uvm_src):
    """Attribution des violations aux entités : par package (fichiers inclus compris), puis par table."""
    tb = os.path.join(HERE, "entities", "tb")
    args = [f"+incdir+{uvm_src}", f"+incdir+{ROOT}", f"+incdir+{tb}/agents/bus",
            f"{uvm_src}/uvm_pkg.sv", f"{ROOT}/checker_base_pkg.sv",
            f"{tb}/agents/bus/bus_agent_pkg.sv", f"{tb}/env/bus_env_pkg.sv", f"{tb}/tests/bus_test_pkg.sv"]
    compiled = compile_sources(args)
    expected_pkg = {"bus_agent_pkg.sv": "bus_agent_pkg", "bus_item.svh": "bus_agent_pkg",
                    "bus_env_pkg.sv": "bus_env_pkg", "bus_test_pkg.sv": "bus_test_pkg"}
    expected_map = {"bus_agent_pkg.sv": "Agent BUS", "bus_item.svh": "Agent BUS",
                    "bus_env_pkg.sv": "Env + tests", "bus_test_pkg.sv": "Env + tests"}
    errors = []
    for cfg_over, expected in (({}, expected_pkg),
                               ({"entities": {"Agent BUS": [f"{tb}/agents/bus/*"],
                                              "Env + tests": [f"{tb}/env/*", f"{tb}/tests/*"]}},
                                expected_map)):
        cfg = config_mod.load()
        cfg.update(cfg_over)
        ctx = Context(compiled.comp, cfg, compiled=compiled,
                      severities={rid: r.severity for rid, r in RULES.items()})
        for r in RULES.values():
            if ctx.severities[r.id] != "off":
                r.fn(ctx)
        seen = set()
        for v in ctx.violations:
            base = os.path.basename(v.file)
            if base in expected:
                seen.add(base)
                got = ctx.entity_of(v.file)
                if got != expected[base]:
                    errors.append(f"{base} : entité {got!r}, attendu {expected[base]!r}")
        errors += [f"aucune violation dans {b} (fixture à revoir)" for b in set(expected) - seen]
    if errors:
        print("ÉCHEC   entités\n   " + "\n   ".join(errors))
        return False
    print("OK      entités (package, fichier inclus, table [entities])")
    return True


def test_kpis(uvm_src):
    """KPI calculés sur le mini testbench à trois entités, vérifiés à la main."""
    import dataclasses
    from uvm_lint import kpi
    tb = os.path.join(HERE, "entities", "tb")
    args = [f"+incdir+{uvm_src}", f"+incdir+{ROOT}", f"+incdir+{tb}/agents/bus",
            f"{uvm_src}/uvm_pkg.sv", f"{ROOT}/checker_base_pkg.sv",
            f"{tb}/agents/bus/bus_agent_pkg.sv", f"{tb}/env/bus_env_pkg.sv", f"{tb}/tests/bus_test_pkg.sv"]
    compiled = compile_sources(args)
    ctx = Context(compiled.comp, config_mod.load(), compiled=compiled,
                  severities={rid: r.severity for rid, r in RULES.items()})
    for r in RULES.values():
        if ctx.severities[r.id] != "off":
            r.fn(ctx)
    viols = [dataclasses.replace(v, entity=ctx.entity_of(v.file)) for v in ctx.violations]
    k = kpi.compute(ctx, viols)
    expected = {
        "bus_agent_pkg": dict(classes=4, factory_pct=75.0, errors=1, warnings=1, check_points=0,
                              sequences=1, virtual_sequences=0, items=1, monitors=1, checkers=0,
                              coverage_collectors=1, covergroups=1, coverpoints=2, crosses=1,
                              bins=2, illegal_ignore_bins=1, constraints=0, markers=0),
        "bus_env_pkg": dict(classes=1, checkers=1, factory_pct=100.0, check_points=1, msg_id_pct=0.0,
                            errors=1, warnings=1, commented_checks=1, disabled_checks=0),
        "bus_test_pkg": dict(classes=1, tests=1, errors=2, warnings=1, disabled_checks=1, markers=3),
    }
    def get(ent, key):
        d = k.get(ent, {}).get("kpi", {})
        return d.get("inventory", {}).get(key, d.get(key))
    errors = [f"{ent}.{key} = {get(ent, key)!r}, attendu {val!r}"
              for ent, exp in expected.items() for key, val in exp.items() if get(ent, key) != val]
    for ent, st in (("bus_agent_pkg", "red"), ("bus_env_pkg", "red"), ("bus_test_pkg", "red")):
        if k.get(ent, {}).get("overall") != st:
            errors.append(f"{ent}.overall = {k.get(ent, {}).get('overall')!r}, attendu {st!r}")
    if errors:
        print("ÉCHEC   KPI\n   " + "\n   ".join(errors))
        return False
    print("OK      KPI (comptages, ratios, statuts)")
    return True


def test_dut():
    """KPI DUT sur un petit RTL vérifié à la main (ctr_top.sv, mem.sv)."""
    import dataclasses
    from uvm_lint import kpi
    d = os.path.join(HERE, "dut", "rtl")
    compiled = compile_sources([f"{d}/ctr_top.sv", f"{d}/mem.sv"])
    ctx = Context(compiled.comp, config_mod.load(), compiled=compiled,
                  severities={rid: r.severity for rid, r in RULES.items()})
    k = kpi.compute(ctx, [])
    # ctr_top.sv : ctr (W=8 et W=16) instancié 2 fois dans top ; entité = premier module (ctr)
    #   ports ctr 4 + top 7 = 11 ; bits de ports ctr(W=8) 11 + top 29 = 40
    #   registres : u0 q8+st2, u1 q16+st2, top x1 = 29 ; 1 FSM (st) ; horloges clk, clk2
    # mem.sv : mem (m 4x8 + q 8 + e_q 4 = 44 bits) et lat (always_latch, pas de bascule)
    expected = {
        "ctr": dict(modules=2, root_modules=1, instances=3, ports=11, port_bits=40, parameters=1,
                    always_ff=2, always_comb=1, always_latch=0, fsm=1, flop_bits=29, clocks=2,
                    rtl_assertions=1),
        "mem": dict(modules=2, root_modules=2, instances=2, ports=8, port_bits=29, always_ff=1,
                    always_latch=1, flop_bits=44, fsm=0, clocks=1),
    }
    errors = []
    for ent, exp in expected.items():
        got = (k.get(ent) or {}).get("kpi", {})
        if got.get("kind") != "dut":
            errors.append(f"{ent}.kind = {got.get('kind')!r}, attendu 'dut'")
        for key, val in exp.items():
            if (got.get("dut") or {}).get(key) != val:
                errors.append(f"{ent}.dut.{key} = {(got.get('dut') or {}).get(key)!r}, attendu {val!r}")
    if (k.get("mem") or {}).get("status", {}).get("dut.always_latch") != "amber":
        errors.append("mem : le latch devrait être orange")
    if (k.get("mem") or {}).get("kpi", {}).get("markers") != 1:
        errors.append("mem : 1 marqueur TODO attendu")
    if errors:
        print("ÉCHEC   DUT\n   " + "\n   ".join(errors))
        return False
    print("OK      DUT (modules, ports, registres, FSM, horloges, latch)")
    return True


def test_git():
    """Activité git : dépôt temporaire avec des commits connus."""
    import subprocess
    import tempfile
    from uvm_lint import gitstats
    with tempfile.TemporaryDirectory() as tmp:
        def g(*a, env=None):
            subprocess.run(["git", "-C", tmp, *a], check=True, capture_output=True,
                           env={**os.environ, **(env or {})})
        g("init", "-q")
        a, b = os.path.join(tmp, "a.sv"), os.path.join(tmp, "b.sv")
        now = int(__import__("time").time())
        steps = [(a, "l1\nl2\nl3\n", "alice", now - 40 * 86400),   # hors fenêtre de 30 j
                 (a, "l1\nl2b\nl3\nl4\n", "bob", now - 10 * 86400),  # +2 -1
                 (b, "x\n", "alice", now - 5 * 86400)]                  # +1
        for path, content, who, ts in steps:
            with open(path, "w") as f:
                f.write(content)
            g("add", "-A")
            g("-c", f"user.name={who}", "-c", "user.email=x@y", "commit", "-q", "-m", "c",
              env={"GIT_AUTHOR_DATE": f"@{ts}", "GIT_COMMITTER_DATE": f"@{ts}"})
        st = gitstats.collect({"A": [a], "AB": [a, b]}, 30)
    errors = []
    exp = {"A": dict(commits=1, lines_added=2, lines_deleted=1, authors=1, days_since_change=10),
           "AB": dict(commits=2, lines_added=3, lines_deleted=1, authors=2, days_since_change=5)}
    for ent, e in exp.items():
        for key, v in e.items():
            if (st.get(ent) or {}).get(key) != v:
                errors.append(f"{ent}.{key} = {(st.get(ent) or {}).get(key)!r}, attendu {v!r}")
    if errors:
        print("ÉCHEC   git\n   " + "\n   ".join(errors))
        return False
    print("OK      git (fenêtre, lignes, auteurs, dernier changement)")
    return True


def test_docs():
    """Garde-fou de maintenance : chaque règle a sa docstring complète et figure dans le README ;
    les fichiers de reprise existent. Voir AGENTS.md, invariant 5."""
    errors = []
    for rid, r in RULES.items():
        doc = r.fn.__doc__ or ""
        if "Fixture" not in doc:
            errors.append(f"{rid} : docstring sans « Fixture : ... » ({r.fn.__name__})")
        if not re.fullmatch(r"[A-Z]+(-[A-Z0-9]+)+", rid):
            errors.append(f"{rid} : identifiant hors format FAMILLE-NOM")
    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    errors += [f"{rid} absente du tableau des règles du README" for rid in RULES if f"| {rid} |" not in readme]
    for f in ("AGENTS.md", "CLAUDE.md", os.path.join(".github", "copilot-instructions.md"), "uvm_lint.toml"):
        if not os.path.exists(os.path.join(ROOT, f)):
            errors.append(f"{f} manquant")
    from uvm_lint import config as cfgmod
    try:
        cfgmod.load(os.path.join(ROOT, "uvm_lint.toml"))
    except Exception as e:
        errors.append(f"uvm_lint.toml invalide : {e}")
    if errors:
        print("ÉCHEC   documentation\n   " + "\n   ".join(errors))
        return False
    print(f"OK      documentation ({len(RULES)} règles documentées et listées)")
    return True


def main(paths):
    """Fixtures, puis tests unitaires (entités, KPI, DUT, git), puis couverture des règles."""
    uvm_home = os.environ.get("UVM_HOME")
    if not uvm_home:
        print("UVM_HOME non défini (doit contenir src/uvm_pkg.sv)")
        return 2
    uvm_src = os.path.join(uvm_home, "src")
    paths_given = bool(paths)
    paths = paths or sorted(glob.glob(os.path.join(HERE, "fixtures", "*.sv")))
    failed, covered = 0, set()
    for p in paths:
        name = os.path.basename(p)
        try:
            got, ctx = run_fixture(p, uvm_src)
        except CompileError as e:
            print(f"ERREUR  {name} : compilation\n{e.report}")
            failed += 1
            continue
        exp = expectations(p)
        covered |= {r for _, r in exp}
        missing, extra = exp - got, got - exp
        msgs = {(v.line, v.rule): v.message for v in ctx.violations}
        if missing or extra:
            failed += 1
            print(f"ÉCHEC   {name}")
            for line, r in sorted(missing):
                print(f"   manquant (faux négatif) : ligne {line} {r}")
            for line, r in sorted(extra):
                print(f"   inattendu (faux positif) : ligne {line} {r} — {msgs.get((line, r), '')}")
        else:
            print(f"OK      {name} ({len(exp)} violation(s) attendue(s))")
    if not paths_given:
        if not test_entities(uvm_src):
            failed += 1
        if not test_kpis(uvm_src):
            failed += 1
        if not test_dut():
            failed += 1
        if not test_git():
            failed += 1
        if not test_docs():
            failed += 1
    uncovered = sorted(set(RULES) - covered)
    if uncovered and len(paths) > 1:
        print(f"\nRègles sans test : {', '.join(uncovered)}")
    print(f"\n{len(paths) - failed}/{len(paths)} fixtures OK")
    return 1 if failed or (uncovered and len(paths) > 1) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
