#!/usr/bin/env python3
"""Reconstruit l'historique des KPI à partir de l'historique git.

Pour chaque date (tous les N jours en remontant), extrait le dernier commit antérieur dans
un worktree temporaire, y lance uvm_lint avec --kpi-date, et ajoute le résultat à
l'historique. Le tableau de bord montre alors immédiatement l'évolution du RTL et du DV.

La filelist modèle utilise @ROOT@ pour la racine du dépôt. Une ligne préfixée par « ? »
n'est gardée que si le fichier existe à ce commit (fichiers ajoutés ou supprimés en cours
de projet) ; « -y @ROOT@/rtl » laisse slang trouver les modules quel que soit leur nombre :
    +incdir+@ROOT@/rtl
    @ROOT@/rtl/my_pkg.sv
    ?@ROOT@/rtl/my_new_pkg.sv
    -y @ROOT@/rtl

Usage :
  python3 tools/kpi_backfill.py --repo <dépôt> --filelist modele.f --history kpi_history.jsonl \\
      [--points 8] [--every 30] [-- options uvm_lint supplémentaires]
"""
import argparse
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def git(repo, *args):
    """git -C repo ... ; lève une exception en cas d'échec."""
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout.strip()


def main():
    """Un worktree détaché par date ; uvm_lint y tourne avec --kpi-date et l'historique commun."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--filelist", required=True, help="filelist modèle contenant @ROOT@")
    ap.add_argument("--history", required=True)
    ap.add_argument("--points", type=int, default=8, help="nombre de points d'historique")
    ap.add_argument("--every", type=int, default=30, help="intervalle entre deux points (jours)")
    ap.add_argument("--git-window", type=int, default=30, help="fenêtre d'activité git de chaque point")
    opts, extra = ap.parse_known_args()
    extra = [a for a in extra if a != "--"]

    repo = git(opts.repo, "rev-parse", "--show-toplevel")
    with open(opts.filelist, encoding="utf-8") as f:
        template = f.read()
    now = datetime.now(timezone.utc)
    dates = [now - timedelta(days=opts.every * i) for i in range(opts.points - 1, 0, -1)]

    for d in dates:
        commit = git(repo, "rev-list", "-1", f"--before={d.isoformat()}", "HEAD")
        if not commit:
            print(f"{d:%Y-%m-%d} : aucun commit antérieur, ignoré")
            continue
        with tempfile.TemporaryDirectory(prefix="kpi_wt_") as tmp:
            wt = os.path.join(tmp, "wt")
            git(repo, "worktree", "add", "--detach", "-q", wt, commit)
            try:
                fl = os.path.join(tmp, "files.f")
                lines = []
                for line in template.replace("@ROOT@", wt).splitlines():
                    if line.startswith("?"):
                        if not os.path.exists(line[1:].strip()):
                            continue
                        line = line[1:]
                    lines.append(line)
                with open(fl, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                cmd = [sys.executable, "-m", "uvm_lint", "--kpi-date", d.isoformat(),
                       "--kpi-history", os.path.abspath(opts.history),
                       "--kpi-git", str(opts.git_window), *extra, "-f", fl]
                r = subprocess.run(cmd, cwd=wt, capture_output=True, text=True,
                                   env={**os.environ, "PYTHONPATH": ROOT, "GIT_COMMIT": commit[:10]})
                status = "OK" if r.returncode in (0, 1) else f"échec (code {r.returncode})"
                print(f"{d:%Y-%m-%d} {commit[:10]} : {status}")
                if r.returncode not in (0, 1):
                    print(r.stdout[-2000:], r.stderr[-2000:], sep="\n")
            finally:
                git(repo, "worktree", "remove", "--force", wt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
