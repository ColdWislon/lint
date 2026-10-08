"""Configuration par défaut, surchargeable par un fichier uvm_lint.toml."""
import copy
import tomllib

DEFAULTS = {
    # classes de base qui font d'une classe un « checker »
    "checker_bases": ["checker_base", "uvm_scoreboard", "uvm_subscriber"],
    # classes de base qui font d'une classe un test
    "test_bases": ["uvm_test"],
    # seules ces classes (et leurs dérivées) peuvent lever des objections
    "objection_allowed_bases": ["uvm_test", "uvm_sequence_base"],
    # packages de tests (glob) : un checker ne doit pas en dépendre
    "test_packages": ["*_test_pkg", "*_tests_pkg", "*_seq_pkg"],
    # code exclu de l'analyse (glob sur le chemin ou le nom de package)
    "exclude_paths": [],
    "exclude_packages": [],
    # entités de vérification : nom -> globs de chemins (première correspondance gagne)
    "entities": {},
    # entité des fichiers non couverts par [entities] : "package" ou "dir"
    "entity_default": "package",
    # fichiers du DUT (globs) et entité par défaut de ces fichiers : "module" ou "dir"
    "dut_paths": ["*/rtl/*", "*/hdl/*", "*/design/*"],
    "dut_entity_default": "module",
    # fenêtre d'activité git (jours) pour --kpi-git
    "churn_days": 30,
    # préfixe des defines de workaround (inventaire --workarounds et règles WA-*)
    "workaround_prefix": "WA_",
    "naming": {
        "message_id": r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$",
        "message_macros": ["uvm_error", "uvm_fatal"],
        "classes": {
            "checker":   r"^[a-z][a-z0-9_]*_(sb|chk|pred)$",
            "test":      r"^[a-z][a-z0-9_]*_test$",
            "env":       r"^[a-z][a-z0-9_]*_env$",
            "agent":     r"^[a-z][a-z0-9_]*_agent$",
            "driver":    r"^[a-z][a-z0-9_]*_(drv|driver)$",
            "monitor":   r"^[a-z][a-z0-9_]*_(mon|monitor)$",
            "sequencer": r"^[a-z][a-z0-9_]*_(sqr|sequencer)$",
            "sequence":  r"^[a-z][a-z0-9_]*_(seq|vseq)$",
            "item":      r"^[a-z][a-z0-9_]*_(item|txn|tr)$",
        },
    },
    # CHK-COMMENTED : ce qui est un « check » quand on le trouve en commentaire (regex)
    "commented_checks": {
        "`uvm_error/`uvm_fatal": r"`uvm_(error|fatal)\s*\(",
        "assertion": r"\b(assert|assume)\s*(property|final|#0)?\s*\(",
        "count_check": r"\bcount_check\s*\(",
        "compare": r"\.compare\s*\(",
        "macro de check": r"`\w*CHECK\w*\s*\(",
        "connexion au checker": r"\.connect\s*\([^)]*\b\w*(sb|scoreboard|chk|checker)\w*",
    },
    # marqueurs de travail en cours dans les commentaires (KPI « marqueurs » et règle CMT-MARKER)
    "markers": ["TODO", "FIXME", "TBC", "TBD", "XXX", "HACK", "BUG", "KLUDGE", "WIP",
                "A FAIRE", "À FAIRE"],
    "markers_case_sensitive": True,
    # KPI par entité : seuils des feux (green / amber / red)
    #   red_above / amber_above : plus bas est meilleur ; red_below / amber_below : plus haut est meilleur
    "kpi": {
        "prefix_in_checkers": True,
        # ce qui compte comme point de contrôle actif (regex sur le source sans commentaires)
        "check_points": {
            "`uvm_error/fatal": r"`uvm_(error|fatal)\s*\(",
            "macros CHECK": r"`\w*CHECK\w*\s*\(",
            "count_check": r"\bcount_check\s*\(",
            "assertions": r"\b(assert|assume)\s*(property|final|#0)?\s*\(",
        },   # un ID conforme dans un checker doit aussi avoir le préfixe de classe
        "thresholds": {
            "errors_per_kloc": {"amber_above": 0, "red_above": 2},
            "factory_pct": {"amber_below": 100, "red_below": 90},
            "msg_id_pct": {"amber_below": 95, "red_below": 80},
            "commented_checks": {"red_above": 0},
            "disabled_checks": {"red_above": 0},
            "wa_active": {"amber_above": 0},
            "wa_dead": {"amber_above": 0},
            "baselined": {"amber_above": 0},
            "dut.always_latch": {"amber_above": 0},
            "dut.slang_warnings": {"amber_above": 0, "red_above": 20},
        },
    },
    # sévérité par règle : "error", "warning" ou "off" (vide = défaut de la règle)
    "rules": {},
}


def _merge(base, over):
    """Fusion récursive : un dict de la config utilisateur complète celui par défaut, une liste le remplace."""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load(path=None):
    """Configuration effective : DEFAULTS + fichier TOML éventuel."""
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        with open(path, "rb") as f:
            _merge(cfg, tomllib.load(f))
    return cfg
