"""Inventaire des workarounds : defines préfixés (WA_ par défaut).

Pour chaque workaround on collecte :
  - où il est défini (`define dans les sources, ou +define+ en ligne de commande)
  - où il est testé (`ifdef / `ifndef / `elsif, y compris la forme `ifdef (A && B))
  - où il est utilisé comme macro (`WA_X)
  - où il est supprimé (`undef)
  - s'il est actif, c'est-à-dire défini à la fin du prétraitement de cette compilation

Le scan est textuel (commentaires et chaînes neutralisés) : il voit aussi les
branches inactives, donc l'inventaire ne dépend pas de la configuration compilée.
"""
import os
import re
from dataclasses import dataclass, field

from .textscan import source_files, strip_comments  # noqa: F401
CMDLINE = "<ligne de commande>"


@dataclass
class Workaround:
    """Un define préfixé : où il est défini / testé / utilisé / supprimé, et s'il est actif."""
    name: str
    defined: list = field(default_factory=list)    # (fichier, ligne, valeur)
    tested: list = field(default_factory=list)     # (fichier, ligne, directive)
    used: list = field(default_factory=list)       # (fichier, ligne)
    undefined: list = field(default_factory=list)  # (fichier, ligne)
    active: bool = False
    value: str = None

    @property
    def status(self):
        if not self.defined:
            return "jamais défini"
        if not self.tested and not self.used:
            return f"{'actif' if self.active else 'inactif'}, jamais testé ni utilisé"
        return "actif" if self.active else "défini mais inactif"

    def as_dict(self):
        return {"name": self.name, "status": self.status, "active": self.active,
                "value": self.value,
                "defined": [{"file": f, "line": l, "value": v} for f, l, v in self.defined],
                "tested": [{"file": f, "line": l, "directive": d} for f, l, d in self.tested],
                "used": [{"file": f, "line": l} for f, l in self.used],
                "undefined": [{"file": f, "line": l} for f, l in self.undefined]}


def scan(files, prefix, predefines, active_macros):
    """Inventaire {nom: Workaround}. predefines : +define+ ; active_macros : macros définies
    en fin de prétraitement (core._final_macros), qui donnent l'état actif."""
    p = re.escape(prefix)
    name = rf"{p}\w*"
    re_define = re.compile(rf"`define\s+({name})\b[ \t]*(.*)")
    re_undef = re.compile(rf"`undef\s+({name})\b")
    re_test = re.compile(rf"`(ifdef|ifndef|elsif)\s+({name})\b")
    re_test_expr = re.compile(r"`(ifdef|ifndef|elsif)\s*\(([^)\n]*)\)")
    re_use = re.compile(rf"`({name})\b")
    re_name = re.compile(rf"\b({name})\b")

    was = {}

    def get(n):
        return was.setdefault(n, Workaround(n))

    for d in predefines:
        n, _, v = d.partition("=")
        if n.startswith(prefix):
            get(n).defined.append((CMDLINE, 0, v or None))

    for path in files:
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                raw = f.read()
        except OSError:
            continue
        if prefix not in raw:
            continue
        clean = strip_comments(raw)
        raw_lines = raw.splitlines()
        for ln, line in enumerate(clean.splitlines(), 1):
            if prefix not in line:
                continue
            for m in re_define.finditer(line):
                value = raw_lines[ln - 1][m.start(2):].split("//")[0].strip() or None
                get(m.group(1)).defined.append((path, ln, value))
            for m in re_undef.finditer(line):
                get(m.group(1)).undefined.append((path, ln))
            for m in re_test.finditer(line):
                get(m.group(2)).tested.append((path, ln, m.group(1)))
            for m in re_test_expr.finditer(line):
                for n in re_name.findall(m.group(2)):
                    get(n).tested.append((path, ln, m.group(1)))
            for m in re_use.finditer(line):
                n = m.group(1)
                # `define / `undef / `ifdef sont déjà traités : pas des utilisations
                before = line[:m.start()].rstrip()
                if re.search(r"`(define|undef|ifdef|ifndef|elsif)$", before):
                    continue
                get(n).used.append((path, ln))

    for n, w in was.items():
        if n in active_macros:
            w.active = True
            w.value = active_macros[n]
    return dict(sorted(was.items()))


def format_text(was, prefix, cwd):
    """Rendu texte de --workarounds."""
    def loc(f, l):
        if f == CMDLINE:
            return CMDLINE
        return f"{os.path.relpath(f, cwd)}:{l}"

    def locs(items, limit=3):
        s = ", ".join(loc(x[0], x[1]) for x in items[:limit])
        return s + (f" (+{len(items) - limit})" if len(items) > limit else "")

    lines = []
    n_active = sum(w.active for w in was.values())
    lines.append(f"Workarounds ({prefix}*) : {len(was)} trouvé(s), {n_active} actif(s) dans cette compilation")
    for w in was.values():
        val = f" = {w.value}" if w.active and w.value else ""
        lines.append(f"\n  {w.name}{val}  [{w.status}]")
        lines.append(f"    défini    : {locs(w.defined) if w.defined else '—'}")
        lines.append(f"    testé     : {len(w.tested)}×  {locs(w.tested) if w.tested else ''}".rstrip())
        lines.append(f"    utilisé   : {len(w.used)}×  {locs(w.used) if w.used else ''}".rstrip())
        if w.undefined:
            lines.append(f"    `undef    : {locs(w.undefined)}")
    return "\n".join(lines)
