"""Tableau de bord HTML autonome des KPI par entité (aucune ressource externe).

Deux sections : environnement de vérification (entités DV) et DUT (entités RTL).
Avec un historique, chaque fiche montre les tendances et l'écart avec le run précédent.
"""
import html
import json

from .kpi import DUT_DEFS, INVENTORY_DEFS, KPI_DEFS

LABELS = {k: (label, unit, sense) for k, label, unit, sense in KPI_DEFS}
LABELS.update({k: (label, "", None) for k, label in INVENTORY_DEFS})
LABELS.update({"dut." + k: (label, "", None) for k, label in DUT_DEFS})
LABELS.update({"git.commits": ("Commits", "", None), "git.lines_added": ("Lignes +", "", None),
               "git.lines_deleted": ("Lignes −", "", None), "git.authors": ("Auteurs", "", None),
               "git.last_change": ("Dernier changement", "", None),
               "git.days_since_change": ("Jours depuis", "", None)})

DV_COLS = ["loc", "tests", "sequences", "coverpoints", "check_points", "errors", "errors_per_kloc",
           "factory_pct", "msg_id_pct", "commented_checks", "disabled_checks", "wa_active", "wa_dead",
           "waivers", "markers"]
DUT_COLS = ["loc", "dut.modules", "dut.instances", "dut.ports", "dut.flop_bits", "dut.fsm",
            "dut.clocks", "dut.always_latch", "dut.rtl_assertions", "dut.slang_warnings", "markers",
            "wa_active", "git.commits", "git.lines_added", "git.lines_deleted", "git.last_change"]
DV_TREND = ["errors", "warnings", "commented_checks", "markers", "check_points", "coverpoints", "tests"]
DUT_TREND = ["loc", "dut.flop_bits", "dut.ports", "dut.instances", "dut.slang_warnings", "markers"]
# écarts avec le run précédent affichés dans les fiches
DV_DELTA = ["loc", "tests", "sequences", "coverpoints", "check_points", "errors", "markers"]
DUT_DELTA = ["loc", "dut.modules", "dut.instances", "dut.ports", "dut.port_bits", "dut.flop_bits",
             "dut.fsm", "dut.always_latch", "dut.rtl_assertions", "dut.slang_warnings", "markers", "wa_active"]

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#e4e3de;
--green:#2e7d4f;--green-bg:#e6f2ea;--amber:#9a6200;--amber-bg:#fbf0d9;--red:#b42318;--red-bg:#fbe7e5;
--accent:#3a5a8c;--up:#3a5a8c;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151514;--card:#1f1f1d;--ink:#ecebe6;
--mute:#9a9992;--line:#33332f;--green:#6cc58f;--green-bg:#1d3326;--amber:#e3ad4f;--amber-bg:#3a2e17;
--red:#f0857a;--red-bg:#3d1f1c;--accent:#8fb0e3;--up:#8fb0e3}}
:root[data-theme="dark"]{--bg:#151514;--card:#1f1f1d;--ink:#ecebe6;--mute:#9a9992;--line:#33332f;
--green:#6cc58f;--green-bg:#1d3326;--amber:#e3ad4f;--amber-bg:#3a2e17;--red:#f0857a;--red-bg:#3d1f1c;
--accent:#8fb0e3;--up:#8fb0e3}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 var(--sans)}
main{max-width:1240px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0}
h3.section{font-size:18px;margin:36px 0 12px;padding-top:18px;border-top:2px solid var(--line)}
.sub{color:var(--mute);margin:0 0 22px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:18px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile b{display:block;font:600 22px/1.2 var(--mono)}.tile span{color:var(--mute);font-size:12px}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px;margin-bottom:10px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th{font-weight:600;color:var(--mute);font-size:11px;text-transform:uppercase;letter-spacing:.03em;
vertical-align:bottom;white-space:normal;min-width:64px}
th:first-child,td:first-child{text-align:left;position:sticky;left:0;background:var(--card)}
tr:last-child td{border-bottom:0}td{font-family:var(--mono)}td:first-child{font-family:var(--sans);font-weight:600}
.v{display:inline-block;min-width:40px;padding:1px 7px;border-radius:5px}
.green{color:var(--green);background:var(--green-bg)}.amber{color:var(--amber);background:var(--amber-bg)}
.red{color:var(--red);background:var(--red-bg)}.na{color:var(--mute)}
.d{font-size:11px;margin-left:4px;color:var(--up)}.d.neg{color:var(--mute)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:1px;background:var(--mute)}
.dot.green{background:var(--green)}.dot.amber{background:var(--amber)}.dot.red{background:var(--red)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.card header{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px}
.badge{font-size:11px;font-weight:600;padding:2px 8px;border-radius:99px}
dl{display:grid;grid-template-columns:1fr auto;gap:4px 12px;margin:0 0 12px}
dt{color:var(--mute)}dd{margin:0;font-family:var(--mono);text-align:right}
.block{font-size:12px;color:var(--mute);border-top:1px solid var(--line);padding-top:10px;margin-top:10px}
.block code{font-family:var(--mono);color:var(--ink)}
.deltas{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.deltas span{font-family:var(--mono);font-size:11px;border:1px solid var(--line);border-radius:5px;padding:1px 6px;color:var(--ink)}
.trend{display:flex;gap:14px;flex-wrap:wrap}
.trend figure{margin:0;font-size:11px;color:var(--mute)}.trend svg{display:block}
.inv{display:grid;grid-template-columns:repeat(auto-fill,minmax(92px,1fr));gap:6px;margin:0 0 12px}
.inv div{border:1px solid var(--line);border-radius:7px;padding:6px 8px}
.inv b{display:block;font:600 16px/1.2 var(--mono)}.inv span{color:var(--mute);font-size:11px}
.legend{color:var(--mute);font-size:12px;margin:0 0 18px}
@media (max-width:520px){.cards{grid-template-columns:1fr}main{padding-top:18px}}
"""

OVERALL = {"red": "À traiter", "amber": "À surveiller", "green": "OK", None: "—"}


def val(d, key):
    """Valeur d'un KPI par clé : kpi, inventaire, dut.*, git.*."""
    k = d["kpi"] if "kpi" in d else d
    if key.startswith("dut."):
        return (k.get("dut") or {}).get(key[4:])
    if key.startswith("git."):
        return (k.get("git") or {}).get(key[4:])
    if key in k.get("inventory", {}):
        return k["inventory"][key]
    return k.get(key)


def _fmt(key, v):
    if v is None:
        return "—"
    unit = LABELS.get(key, ("", "", None))[1]
    if isinstance(v, float):
        return f"{v:g}{unit}"
    return f"{v}{unit}"


def _delta(cur, prev):
    if isinstance(cur, bool) or not isinstance(cur, (int, float)) or not isinstance(prev, (int, float)) \
            or cur == prev:
        return ""
    diff = cur - prev
    diff_s = f"{diff:+g}" if isinstance(diff, float) else f"{diff:+d}"
    return f'<span class="d{" neg" if diff < 0 else ""}">{diff_s}</span>'


def _cell(key, d, prev):
    v, st = val(d, key), d["status"].get(key)
    cls = st or ("na" if v is None else "")
    dl = _delta(v, val(prev, key)) if prev and key in ("loc", "dut.flop_bits", "dut.ports") else ""
    return f'<td><span class="v {cls}">{html.escape(_fmt(key, v))}</span>{dl}</td>'


def _spark(values, w=90, h=26):
    vals = [0 if not isinstance(v, (int, float)) else v for v in values]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = " ".join(f"{i * (w - 4) / (len(vals) - 1) + 2:.1f},{h - 3 - (v - lo) * (h - 6) / span:.1f}"
                   for i, v in enumerate(vals))
    last = pts.split()[-1].split(",")
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" aria-hidden="true">'
            f'<polyline points="{pts}" fill="none" stroke="var(--accent)" stroke-width="1.6"/>'
            f'<circle cx="{last[0]}" cy="{last[1]}" r="2.4" fill="var(--accent)"/></svg>')


def _table(names, kpis, cols, prev_of):
    head = "".join(f"<th>{html.escape(LABELS[k][0])}</th>" for k in cols)
    rows = []
    for n in names:
        d = kpis[n]
        rows.append(f'<tr><td><span class="dot {d["overall"] or ""}"></span>{html.escape(n)}</td>'
                    + "".join(_cell(k, d, prev_of(n)) for k in cols) + "</tr>")
    return (f'<div class="wrap"><table><thead><tr><th>Entité</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _git_block(k):
    g = k.get("git")
    if not g:
        return ""
    shallow = " (clone partiel : historique peut-être incomplet)" if g.get("is_shallow") else ""
    since = f' (il y a {g["days_since_change"]} j)' if g.get("days_since_change") is not None else ""
    return (f'<div class="block">Activité git sur {g["window_days"]} j{shallow} : '
            f'<code>{g["commits"]}</code> commit(s), <code>+{g["lines_added"]}</code> / '
            f'<code>−{g["lines_deleted"]}</code> lignes, <code>{g["authors"]}</code> auteur(s) · '
            f'dernier changement <code>{g["last_change"] or "—"}</code>{since}</div>')


def _history_blocks(n, d, history, trend_keys, delta_keys):
    out = ""
    series = [h["entities"].get(n) for h in history]
    prev = series[-2] if len(series) >= 2 else None
    if prev:
        chips = []
        for key in delta_keys:
            dl = _delta(val(d, key), val(prev, key))
            if dl:
                chips.append(f"<span>{html.escape(LABELS[key][0])} {dl}</span>")
        out += ('<div class="block">Depuis le run précédent : '
                + (f'<div class="deltas">{"".join(chips)}</div>' if chips else "aucun changement")
                + "</div>")
    if sum(s is not None for s in series) >= 2:
        figs = []
        for key in trend_keys:
            vals = [val(s, key) if s else None for s in series]
            figs.append(f"<figure>{_spark(vals)}<figcaption>{html.escape(LABELS[key][0])} : "
                        f"{_fmt(key, vals[-1])}</figcaption></figure>")
        out += f'<div class="block"><div class="trend">{"".join(figs)}</div></div>'
    return out


def _dl(items):
    return "<dl>" + "".join(f"<dt>{html.escape(a)}</dt><dd>{html.escape(str(b))}</dd>" for a, b in items) + "</dl>"


def _card(n, d, body):
    st = d["overall"]
    return (f'<section class="card"><header><h2>{html.escape(n)}</h2>'
            f'<span class="badge {st or "na"}">{OVERALL[st]}</span></header>{body}</section>')


def _dv_card(n, d, history):
    k = d["kpi"]
    inv = k["inventory"]
    inv_html = "".join(f'<div><b>{inv[key]}</b><span>{html.escape(label)}</span></div>'
                       for key, label in INVENTORY_DEFS if inv.get(key))
    items = [("Fichiers", k["files"]), ("Lignes de code", k["loc"]), ("Classes", k["classes"]),
             ("Points de contrôle",
              " · ".join(f"{a} {b}" for a, b in k["check_points_by_kind"].items() if b) or "0"),
             ("Erreurs · warnings", f'{k["errors"]} · {k["warnings"]}'),
             ("Erreurs / kLOC", _fmt("errors_per_kloc", k["errors_per_kloc"])),
             ("Enregistrement factory", _fmt("factory_pct", k["factory_pct"])),
             ("ID de messages conformes", _fmt("msg_id_pct", k["msg_id_pct"])),
             ("Checks commentés",
              f'{k["commented_checks"]} ({_fmt("commented_checks_pct", k["commented_checks_pct"])})'),
             ("Désactivations de checks", k["disabled_checks"]),
             ("Workarounds : total · actifs · morts", f'{k["wa_total"]} · {k["wa_active"]} · {k["wa_dead"]}'),
             ("Waivers", k["waivers"]),
             ("Marqueurs", " · ".join(f"{a} {b}" for a, b in k["markers_by_kind"].items()) or "0"),
             ("Dette (baseline)", k["baselined"])]
    rules = ", ".join(f"<code>{html.escape(r)}</code> ({c})" for r, c in d["top_rules"]) or "aucune violation"
    return _card(n, d, (f'<div class="inv">{inv_html}</div>' if inv_html else "") + _dl(items)
                 + f'<div class="block">Règles les plus fréquentes : {rules}</div>'
                 + _git_block(k) + _history_blocks(n, d, history, DV_TREND, DV_DELTA))


def _dut_card(n, d, history):
    k, dk = d["kpi"], d["kpi"]["dut"]
    items = [("Fichiers · lignes", f'{k["files"]} · {k["loc"]}'),
             ("Modules (dont non instanciés)", f'{dk["modules"]} ({dk["root_modules"]})'),
             ("Interfaces RTL", dk["interfaces_rtl"]),
             ("Instances (élaboré)", dk["instances"]),
             ("Ports · bits de ports", f'{dk["ports"]} · {dk["port_bits"]}'),
             ("Paramètres", dk["parameters"]),
             ("Blocs séquentiels · comb · latch · autres",
              f'{dk["always_ff"]} · {dk["always_comb"]} · {dk["always_latch"]} · {dk["always_other"]}'),
             ("Bits de registres (élaboré)", dk["flop_bits"]),
             ("FSM · horloges", f'{dk["fsm"]} · {dk["clocks"]}'),
             ("Assertions dans le RTL", dk["rtl_assertions"]),
             ("Warnings slang", dk["slang_warnings"]),
             ("Marqueurs", " · ".join(f"{a} {b}" for a, b in k["markers_by_kind"].items()) or "0"),
             ("Workarounds : total · actifs · morts", f'{k["wa_total"]} · {k["wa_active"]} · {k["wa_dead"]}')]
    codes = ", ".join(f"<code>{html.escape(c)}</code> ({c_n})" for c, c_n in dk["warning_codes"]) or "aucun"
    return _card(n, d, _dl(items) + f'<div class="block">Warnings slang les plus fréquents : {codes}</div>'
                 + _git_block(k) + _history_blocks(n, d, history, DUT_TREND, DUT_DELTA))


def _tiles(items):
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><b>{html.escape(str(v))}</b><span>{html.escape(t)}</span></div>'
        for t, v in items) + "</div>"


def render(kpis, title="KPI vérification", subtitle="", history=None):
    """Page HTML complète. history : runs jusqu'au run courant inclus (le dernier = courant).

    Sections affichées seulement si non vides : DV (entités avec du contenu de vérification),
    DUT (entités kind == "dut"). Les données brutes sont embarquées dans #kpi-data pour
    qu'un autre outil puisse relire la page."""
    history = history or []
    prev_rec = history[-2]["entities"] if len(history) >= 2 else {}

    def prev_of(n):
        return prev_rec.get(n)

    def has_dv_content(d):
        k = d["kpi"]
        return any(val(d, key) for key in ("classes", "check_points", "errors", "warnings", "coverpoints",
                                           "covergroups", "interfaces", "markers", "wa_total"))
    dv = [n for n, d in kpis.items() if d["kpi"].get("kind") != "dut" and has_dv_content(d)]
    dut = [n for n, d in kpis.items() if d["kpi"].get("kind") == "dut" and d["kpi"].get("dut")]
    rank = {"red": 0, "amber": 1, "green": 2}
    dv.sort(key=lambda n: (rank.get(kpis[n]["overall"], 3), -(kpis[n]["kpi"]["errors"] or 0), n))
    dut.sort(key=lambda n: (-((kpis[n]["kpi"].get("git") or {}).get("commits") or 0),
                            -(kpis[n]["kpi"]["dut"]["flop_bits"]), n))

    def tot(names, key):
        return sum(v for v in (val(kpis[n], key) for n in names)
                   if isinstance(v, (int, float)) and not isinstance(v, bool))

    parts = []
    if dv:
        parts.append('<h3 class="section">Environnement de vérification</h3>')
        parts.append(_tiles([
            ("Entités", len(dv)), ("Entités à traiter", sum(kpis[n]["overall"] == "red" for n in dv)),
            ("Lignes de code", tot(dv, "loc")), ("Tests", tot(dv, "tests")), ("Séquences", tot(dv, "sequences")),
            ("Covergroups · coverpoints", f'{tot(dv, "covergroups")} · {tot(dv, "coverpoints")}'),
            ("Points de contrôle", tot(dv, "check_points")), ("Erreurs lint", tot(dv, "errors")),
            ("Checks commentés", tot(dv, "commented_checks")), ("Désactivations", tot(dv, "disabled_checks")),
            ("Workarounds actifs", tot(dv, "wa_active")), ("Marqueurs TODO/FIXME…", tot(dv, "markers"))]))
        parts.append(_table(dv, kpis, DV_COLS, prev_of))
        parts.append('<p class="legend">Couleurs selon <code>[kpi.thresholds]</code> ; sans couleur = KPI '
                     'informatif. Tri : à traiter, à surveiller, OK.</p>')
        parts.append('<div class="cards">' + "".join(_dv_card(n, kpis[n], history) for n in dv) + "</div>")
    if dut:
        has_git = any(kpis[n]["kpi"].get("git") for n in dut)
        window = next((kpis[n]["kpi"]["git"]["window_days"] for n in dut if kpis[n]["kpi"].get("git")), None)
        parts.append('<h3 class="section">DUT (RTL)</h3>')
        tiles = [("Entités RTL", len(dut)), ("Modules", tot(dut, "dut.modules")),
                 ("Instances", tot(dut, "dut.instances")), ("Lignes de code", tot(dut, "loc")),
                 ("Bits de registres", tot(dut, "dut.flop_bits")), ("Bits de ports", tot(dut, "dut.port_bits")),
                 ("FSM", tot(dut, "dut.fsm")), ("Warnings slang", tot(dut, "dut.slang_warnings"))]
        if has_git:
            tiles += [(f"Commits ({window} j, somme par entité)", tot(dut, "git.commits")),
                      (f"Lignes modifiées ({window} j)",
                       f'+{tot(dut, "git.lines_added")} / −{tot(dut, "git.lines_deleted")}')]
        parts.append(_tiles(tiles))
        cols = DUT_COLS if has_git else [c for c in DUT_COLS if not c.startswith("git.")]
        parts.append(_table(dut, kpis, cols, prev_of))
        parts.append('<p class="legend">Tri : entités les plus actives (commits) puis les plus grosses '
                     '(bits de registres). Petits chiffres bleus : écart avec le run précédent. '
                     'Ports, blocs, FSM : par définition de module ; instances et bits de registres : '
                     'design élaboré avec ses paramètres effectifs.</p>')
        parts.append('<div class="cards">' + "".join(_dut_card(n, kpis[n], history) for n in dut) + "</div>")

    data = json.dumps(kpis, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>{CSS}</style></head><body><main>
<h1>{html.escape(title)}</h1><p class="sub">{html.escape(subtitle)}</p>
{"".join(parts)}
<script type="application/json" id="kpi-data">{data}</script>
</main></body></html>"""
