"""Évolution des sources via git : activité par entité sur une fenêtre glissante."""
import os
import subprocess
import time
from collections import defaultdict


def _git(root, args, timeout=120):
    """Lance git ; None en cas d'échec (pas de dépôt, git absent) : l'activité devient None, pas une erreur."""
    try:
        r = subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                           timeout=timeout, errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _repo_root(path, cache):
    """Racine du dépôt git contenant un fichier (mise en cache par dossier)."""
    d = os.path.dirname(os.path.realpath(path))
    if d not in cache:
        out = _git(d, ["rev-parse", "--show-toplevel"])
        cache[d] = os.path.realpath(out.strip()) if out else None
    return cache[d]


def collect(files_by_entity, days, until=None):
    """{entité: {commits, lines_added, lines_deleted, authors, last_change, days_since_change,
    is_shallow}} ; None pour une entité hors dépôt git.

    `until` (timestamp) fixe la fin de la fenêtre : indispensable pour reconstruire l'historique
    (tools/kpi_backfill.py), sinon la fenêtre serait relative à aujourd'hui. Un fichier peut
    compter pour plusieurs entités. Les chemins sont passés par paquets de 400 (limite de
    longueur de ligne de commande)."""
    roots, by_root = {}, defaultdict(set)
    file_entity = defaultdict(list)          # un fichier peut compter pour plusieurs entités
    for ent, files in files_by_entity.items():
        for f in files:
            real = os.path.realpath(f)
            root = _repo_root(real, roots)
            if root:
                by_root[root].add(os.path.relpath(real, root))
                file_entity[(root, os.path.relpath(real, root))].append(ent)

    stats = {ent: None for ent in files_by_entity}
    now = until or time.time()
    since_arg = f"--since=@{int(now - days * 86400)}"
    until_arg = f"--until=@{int(now)}"
    for root, rels in by_root.items():
        shallow = (_git(root, ["rev-parse", "--is-shallow-repository"]) or "").strip() == "true"
        acc = defaultdict(lambda: {"commits": set(), "lines_added": 0, "lines_deleted": 0,
                                   "authors": set(), "last_change": 0})
        rels = sorted(rels)
        for i in range(0, len(rels), 400):              # limite de longueur de ligne de commande
            chunk = rels[i:i + 400]
            out = _git(root, ["log", since_arg, until_arg, "--numstat", "--no-renames",
                              "--format=%x01%H%x09%an%x09%at", "--", *chunk])
            if out is None:
                continue
            commit = author = ts = None
            for line in out.splitlines():
                if line.startswith("\x01"):
                    commit, author, ts = line[1:].split("\t")
                    ts = int(ts)
                elif line.strip() and commit:
                    parts = line.split("\t")
                    if len(parts) != 3:
                        continue
                    for ent in file_entity.get((root, parts[2]), ()):
                        a = acc[ent]
                        a["commits"].add(commit)
                        a["authors"].add(author)
                        a["lines_added"] += int(parts[0]) if parts[0].isdigit() else 0
                        a["lines_deleted"] += int(parts[1]) if parts[1].isdigit() else 0
                        a["last_change"] = max(a["last_change"], ts)
        # dernier changement, même hors fenêtre
        ents = {ent for r in rels for ent in file_entity[(root, r)]}
        for ent in ents:
            paths = [r for r in rels if ent in file_entity[(root, r)]]
            last = 0
            for i in range(0, len(paths), 400):
                out = _git(root, ["log", "-1", until_arg, "--format=%at", "--", *paths[i:i + 400]])
                if out and out.strip().isdigit():
                    last = max(last, int(out.strip()))
            a = acc[ent]
            stats[ent] = {
                "window_days": days,
                "commits": len(a["commits"]),
                "lines_added": a["lines_added"],
                "lines_deleted": a["lines_deleted"],
                "authors": len(a["authors"]),
                "last_change": time.strftime("%Y-%m-%d", time.localtime(last)) if last else None,
                "days_since_change": int((now - last) // 86400) if last else None,
                "is_shallow": shallow,
            }
    return stats
