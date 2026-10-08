"""Scan textuel des sources : fichiers chargés par slang, commentaires."""
import fnmatch
import os
import re

SOURCE_EXT = {".sv", ".svh", ".v", ".vh", ".svi", ".svp", ".inc"}


# Scan textuel : utilisé là où l'AST ne suffit pas (commentaires, branches `ifdef inactives,
# defines). Les lignes sont conservées pour que les numéros de ligne restent justes.
def strip_comments(src):
    """Remplace commentaires et contenu des chaînes par des espaces (lignes conservées)."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", src[i:j]))
            i = j
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"' and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append('"' + " " * max(0, j - i - 2) + ('"' if j - i >= 2 else ""))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def extract_comments(src):
    """Liste (ligne, texte) du contenu des commentaires, une entrée par ligne de commentaire.

    Les « // » à l'intérieur d'une chaîne ne sont pas des commentaires."""
    out, i, n, line = [], 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append((line, src[i + 2:j]))
            i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j
            for k, part in enumerate(src[i + 2:j].split("\n")):
                out.append((line + k, re.sub(r"^\s*\*(?!/)", "", part) if k else part))
            line += src[i:j].count("\n")
            i = j + 2
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"' and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            i = j + 1 if j < n and src[j] == '"' else j
        else:
            i += 1
    return out


def source_files(sm, exclude_paths, exclude_dirs=()):
    """Fichiers sources réellement chargés par slang (includes compris), sans les filelists
    ni les buffers internes. exclude_dirs : en pratique le dossier de UVM."""
    files = []
    for b in sm.getAllBuffers():
        path = sm.getFullPath(b)
        path = str(path) if path is not None else ""
        if not path or path.startswith("<") or os.path.splitext(path)[1].lower() not in SOURCE_EXT:
            continue
        if any(fnmatch.fnmatch(path, pat) for pat in exclude_paths):
            continue
        if any(os.path.realpath(path).startswith(d + os.sep) for d in exclude_dirs):
            continue
        if path not in files:
            files.append(path)
    return files




def marker_regex(markers, case_sensitive=True):
    """Marqueurs en mots entiers : TODO oui, TODOS / todolist non."""
    alt = "|".join(re.escape(m) for m in sorted(markers, key=len, reverse=True))
    return re.compile(rf"(?<![\w])({alt})(?![\w])", 0 if case_sensitive else re.I)


def find_markers(src, rx):
    """(ligne, marqueur, texte du commentaire) pour chaque marqueur trouvé dans un commentaire."""
    out = []
    for line, txt in extract_comments(src):
        for m in rx.finditer(txt):
            out.append((line, m.group(1).upper() if rx.flags & re.I else m.group(1), txt.strip()))
    return out
