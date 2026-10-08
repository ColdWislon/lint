"""Socle commun : compilation slang, classification des classes UVM, rapport, waivers.

Flux : compile_sources() -> Compiled -> Context(comp, config) -> règles (rules.py) qui
appellent ctx.report() / ctx.report_at() -> ctx.violations -> cli.py (entités, baseline,
sorties, KPI).

Les remarques « PIÈGE pyslang » signalent des comportements de pyslang 12 contre-intuitifs,
vérifiés à l'exécution. Les relire avant de modifier le code voisin ; `grep -n "PIÈGE"`.
"""
import fnmatch
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field

from pyslang import DiagnosticEngine
from pyslang.ast import ExpressionKind, SymbolKind, VisitAction
from pyslang.driver import CommandLineOptions, Driver

WAIVE = re.compile(r"(?:uvm|chk)-waive:\s*([A-Z0-9_\-, ]+)")


@dataclass(frozen=True)
class Violation:
    """Une violation. frozen : dédoublonnée par set() (une classe paramétrée analysée dans
    plusieurs spécialisations produit la même violation plusieurs fois)."""
    file: str
    line: int
    rule: str
    severity: str
    message: str
    entity: str = ""

    def fingerprint(self):
        # sans numéro de ligne : une baseline survit aux modifications du fichier
        return f"{self.file}|{self.rule}|{self.message}"


class CompileError(Exception):
    """Erreur de compilation slang : `report` contient les diagnostics formatés (code 2 en CLI)."""

    def __init__(self, report):
        super().__init__(report)
        self.report = report


@dataclass
class Compiled:
    """Résultat de compile_sources(). Les defines servent à l'inventaire des workarounds."""
    comp: object
    predefines: list          # +define+ de la ligne de commande et des filelists
    macros: dict              # macros définies en fin de prétraitement : nom -> valeur


def _final_macros(driver):
    """Table des macros en fin de prétraitement.

    PIÈGE pyslang : Driver.reportMacros() écrit en C++ directement sur le descripteur 1 ;
    sys.stdout ne la voit pas. On redirige le fd 1 vers un fichier temporaire le temps de
    l'appel. À appeler après parseAllSources() et avant createCompilation()."""
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as tf:
        sys.stdout.flush()
        saved = os.dup(1)
        os.dup2(tf.fileno(), 1)
        try:
            driver.reportMacros()
        finally:
            sys.stdout.flush()
            os.dup2(saved, 1)
            os.close(saved)
        tf.seek(0)
        out = tf.read()
    macros = {}
    for line in out.splitlines():
        name, _, value = line.strip().partition(" ")
        if name and not name.startswith("`"):
            macros[name.split("(")[0]] = value.strip() or None
    return macros


def compile_sources(slang_args):
    """Compile avec les arguments slang de la ligne de commande (-f, +incdir+, +define+, -y...).

    Lève CompileError s'il reste une erreur : les règles supposent un design élaboré complet.
    Les warnings slang ne bloquent pas (ils alimentent le KPI DUT « warnings slang »)."""
    driver = Driver()
    driver.addStandardArgs()
    if not driver.parseCommandLine(" ".join(["slang"] + slang_args), CommandLineOptions()):
        raise CompileError("arguments slang invalides")
    if not (driver.processOptions() and driver.parseAllSources()):
        raise CompileError("échec de lecture des sources")
    predefines = list(driver.createOptionBag().preprocessorOptions.predefines)
    macros = _final_macros(driver)
    comp = driver.createCompilation()
    comp.getRoot()
    errs = [d for d in comp.getAllDiagnostics() if d.isError()]
    if errs:
        raise CompileError(DiagnosticEngine.reportAll(comp.sourceManager, errs))
    return Compiled(comp, predefines, macros)


def text(node):
    """Texte source d'une expression, en traversant les conversions implicites.

    PIÈGE pyslang : les conversions implicites (enum -> int, littéral -> string, void'(...))
    sont des nœuds Conversion sans syntaxe ; str(node.syntax) planterait ou renverrait ""."""
    while node is not None and node.syntax is None and node.kind == ExpressionKind.Conversion:
        node = node.operand
    return str(node.syntax).strip() if node is not None and node.syntax is not None else ""


def unwrap(expr):
    """Retire les nœuds Conversion (implicites ou void'(...)) autour d'une expression."""
    while expr.kind == ExpressionKind.Conversion:
        expr = expr.operand
    return expr


def class_chain(cls):
    """Classes de base, de la plus proche à la plus lointaine."""
    base = getattr(cls, "baseClass", None)
    while base is not None:
        yield base
        base = getattr(base, "baseClass", None)


def own_type_id(cls):
    """typedef `type_id` déclaré dans la classe elle-même (preuve d'enregistrement factory).

    On itère les membres propres plutôt que cls.find() : find() remonte l'héritage et
    trouverait le type_id du parent (faux négatif sur une classe dérivée non enregistrée)."""
    m = next((x for x in cls if x.name == "type_id"), None)
    return m if m is not None and m.kind == SymbolKind.TypeAlias else None


def walk(node, fn):
    """Visite récursive : fn(n) est appelée pour chaque symbole/statement/expression."""
    def cb(n):
        fn(n)
        return VisitAction.Advance
    node.visit(cb)


@dataclass
class Context:
    """État partagé par toutes les règles et les KPI pour une compilation.

    classes   : classes utilisateur (UVM, std et exclusions retirées), spécialisations comprises
    packages  : packages utilisateur
    violations: rempli par report()/report_at() ; cli.py ajoute ensuite l'entité
    severities: règle -> "error" | "warning" | "off" (config + défaut de la règle)
    rule_filter: prédicat --rules, ou None
    """
    comp: object
    config: dict
    compiled: object = None
    sm: object = None
    classes: list = field(default_factory=list)
    packages: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    _lines: dict = field(default_factory=dict)
    _workarounds: dict = None
    _file_pkg: dict = None
    rule_filter: object = None
    severities: dict = field(default_factory=dict)

    def __post_init__(self):
        self.sm = self.comp.sourceManager
        root = self.comp.getRoot()
        seen, found, pkgs = set(), [], []

        def add(c):
            if c is None or c.isInterface:
                return
            key = (c.hierarchicalPath, c.location.offset)
            if key not in seen:
                seen.add(key)
                found.append(c)

        def cb(s):
            if s.kind == SymbolKind.ClassType:
                add(s)
            elif s.kind == SymbolKind.GenericClassDef:
                # classe paramétrée : on analyse au moins sa spécialisation par défaut.
                # PIÈGE pyslang : s.defaultSpecialization est une propriété mal liée qui exige
                # un Scope ; on appelle son getter directement avec le scope parent.
                try:
                    add(type(s).defaultSpecialization.fget(s, s.parentScope))
                except Exception:
                    pass
            elif s.kind == SymbolKind.Package:
                pkgs.append(s)
            return VisitAction.Advance

        root.visit(cb)
        self.classes = [c for c in found if not self.is_excluded(c)]
        self.packages = [p for p in pkgs if not self.is_excluded(p)]

    # ---------- filtrage ----------
    def is_excluded(self, sym):
        """UVM, std, exclude_packages et exclude_paths : jamais analysés par les règles."""
        path = sym.hierarchicalPath
        if path.startswith("uvm_pkg::") or path == "uvm_pkg" or path.startswith("std::"):
            return True
        pkg = self.package_of(sym)
        if any(fnmatch.fnmatch(pkg, p) for p in self.config["exclude_packages"]):
            return True
        fname = self.file_of(sym.location)
        return any(fnmatch.fnmatch(fname, p) for p in self.config["exclude_paths"])

    @staticmethod
    def package_of(sym):
        """Package d'un symbole d'après son chemin hiérarchique ("" hors package)."""
        path = sym.hierarchicalPath
        return path.split("::")[0] if "::" in path else ""

    # ---------- localisation ----------
    def file_of(self, loc):
        """Fichier d'une position. getFullyExpandedLoc : pour du code issu d'une macro, c'est
        le fichier où la macro est appelée (getFullyOriginalLoc donnerait uvm_message_defines.svh)."""
        return str(self.sm.getFileName(self.sm.getFullyExpandedLoc(loc)))

    def is_macro_generated(self, sym):
        """Symbole produit par une macro (`uvm_component_utils génère get_type, create...)."""
        return self.sm.isMacroLoc(sym.location)

    def methods(self, cls):
        """Méthodes écrites par l'utilisateur (hors built-in et code généré par macro)."""
        for m in cls:
            if m.kind != SymbolKind.Subroutine:
                continue
            # méthodes built-in (randomize, srandom...) : pas de syntaxe source.
            # PIÈGE pyslang : ne pas tester m.flags & MethodFlags.BuiltIn, l'enum n'accepte pas
            # les combinaisons de bits et lève ValueError ; idem VariableFlags (const est testé
            # sur le texte source dans la règle UVM-STATIC-STATE).
            if m.syntax is None or self.is_macro_generated(m):
                continue
            yield m

    # ---------- classification ----------
    # La classification repose sur le NOM des classes de base UVM (pas sur l'identité des
    # symboles) : robuste aux spécialisations paramétrées, et suffisant car uvm_pkg est exclu.
    def chain_names(self, cls):
        """Noms de toutes les classes de base."""
        return {b.name for b in class_chain(cls)}

    def derives(self, cls, names):
        """Vrai si l'une des classes de base porte l'un de ces noms."""
        return bool(self.chain_names(cls) & set(names))

    def is_component(self, cls):  # noqa: D102 — les is_* suivants sont explicites par leur nom
        return self.derives(cls, {"uvm_component"})

    def is_object(self, cls):
        return self.derives(cls, {"uvm_object"}) and not self.is_component(cls)

    def is_test(self, cls):
        return self.derives(cls, self.config["test_bases"])

    def is_sequence(self, cls):
        return self.derives(cls, {"uvm_sequence_base"})

    def is_coverage_collector(self, cls):
        """Subscriber qui déclare un covergroup et ne dérive d'aucune base checker explicite."""
        strong = set(self.config["checker_bases"]) - {"uvm_subscriber"}
        if self.derives(cls, strong) or not self.derives(cls, {"uvm_subscriber"}):
            return False
        return any(m.kind == SymbolKind.CovergroupType for c in [cls, *class_chain(cls)] for m in c)

    def is_checker(self, cls):
        """Dérive d'une checker_base (config), n'en est pas une, et n'est pas un collecteur de
        couverture. Les classes listées dans checker_bases elles-mêmes ne sont pas des checkers."""
        bases = set(self.config["checker_bases"])
        return cls.name not in bases and self.derives(cls, bases) and not self.is_coverage_collector(cls)

    def is_checker_type(self, t):
        """Comme is_checker, pour un Type d'expression (bases comprises : utile pour create())."""
        t = getattr(t, "canonicalType", t)
        if t is None or not t.isClass:
            return False
        bases = set(self.config["checker_bases"])
        return t.name in bases or (self.derives(t, bases) and not self.is_coverage_collector(t))

    def role(self, cls):
        """Rôle UVM d'une classe, pour les conventions de nommage."""
        chain = self.chain_names(cls)
        if self.is_coverage_collector(cls):
            return "coverage"
        if self.is_checker(cls):
            return "checker"
        for role, base in (("test", "uvm_test"), ("env", "uvm_env"), ("agent", "uvm_agent"),
                           ("driver", "uvm_driver"), ("monitor", "uvm_monitor"),
                           ("sequencer", "uvm_sequencer_base"), ("sequence", "uvm_sequence_base"),
                           ("item", "uvm_sequence_item")):
            if base in chain:
                return role
        return None

    def source_line(self, loc):
        """Ligne de texte source d'une position (pour les tests textuels ponctuels)."""
        loc = self.sm.getFullyExpandedLoc(loc)
        fname, line = str(self.sm.getFileName(loc)), self.sm.getLineNumber(loc)
        lines = self._read(fname)
        return lines[line - 1] if 0 < line <= len(lines) else ""

    def _read(self, fname):
        if fname not in self._lines:
            try:
                with open(fname, encoding="utf-8", errors="replace") as f:
                    self._lines[fname] = f.read().splitlines()
            except OSError:
                self._lines[fname] = []
        return self._lines[fname]

    # ---------- entités ----------
    def entity_of(self, fname):
        """Entité de vérification d'un fichier.

        1. table [entities] de la config (globs sur le chemin, première correspondance)
        2. sinon, selon entity_default : "package" (package SV déclaré ou inclus dans le
           fichier), "dir" (dossier parent) ; le package retombe sur le dossier pour les
           fichiers hors package (modules, interfaces)."""
        if fname.startswith("<"):
            return fname
        real = os.path.realpath(fname)
        rel = os.path.relpath(real)
        for name, globs in self.config["entities"].items():
            if any(fnmatch.fnmatch(real, g) or fnmatch.fnmatch(rel, g) for g in globs):
                return name
        from .dut import is_dut_file
        if is_dut_file(real, self.config):
            if self.config["dut_entity_default"] == "module":
                mod = self._files_to_modules().get(real) or self._files_to_packages().get(real)
                if mod:
                    return mod
            return os.path.basename(os.path.dirname(real)) or "."
        if self.config["entity_default"] == "package":
            pkg = self._files_to_packages().get(real)
            if pkg:
                return pkg
        return os.path.basename(os.path.dirname(real)) or "."

    def _files_to_modules(self):
        """Fichier -> premier module/interface qu'il déclare (ordre du fichier)."""
        if getattr(self, "_file_mod", None) is None:
            found = {}
            for d in self.comp.getDefinitions():
                if d.kind != SymbolKind.Definition:
                    continue
                f = os.path.realpath(self.file_of(d.location))
                if f not in found or d.location.offset < found[f][0]:
                    found[f] = (d.location.offset, d.name)
            self._file_mod = {f: name for f, (_, name) in found.items()}
        return self._file_mod

    def _files_to_packages(self):
        """Fichier -> package : fichier qui déclare le package, et fichiers `include dedans
        (on les retrouve via la position des classes qu'ils contiennent)."""
        if self._file_pkg is None:
            self._file_pkg = {}
            for p in self.packages:
                self._file_pkg.setdefault(os.path.realpath(self.file_of(p.location)), p.name)
            for c in self.classes:          # fichiers `include dans un package
                pkg = self.package_of(c)
                if pkg:
                    self._file_pkg.setdefault(os.path.realpath(self.file_of(c.location)), pkg)
        return self._file_pkg

    # ---------- workarounds ----------
    @property
    def workarounds(self):
        """Inventaire WA_* (workarounds.scan), calculé une fois et partagé règles / KPI."""
        if self._workarounds is None:
            from . import workarounds
            files = workarounds.source_files(self.sm, self.config["exclude_paths"])
            self._workarounds = workarounds.scan(
                files, self.config["workaround_prefix"],
                self.compiled.predefines if self.compiled else [],
                self.compiled.macros if self.compiled else {})
        return self._workarounds

    # ---------- rapport ----------
    def report_at(self, rule, fname, line, message):
        """Rapport sur un fichier/ligne connus (pas de SourceLocation : scan textuel, ligne de commande)."""
        if self.rule_filter is not None and not self.rule_filter(rule):
            return
        sev = self.severities.get(rule, "error")
        if sev == "off" or (line > 0 and self._waived(fname, line, rule)):
            return
        self.violations.append(Violation(fname, line, rule, sev, message))

    def report(self, rule, loc, message):
        """Point d'entrée des règles AST : applique filtre --rules, sévérité, waiver."""
        if self.rule_filter is not None and not self.rule_filter(rule):
            return
        sev = self.severities.get(rule, "error")
        if sev == "off":
            return
        loc = self.sm.getFullyExpandedLoc(loc)
        fname, line = str(self.sm.getFileName(loc)), self.sm.getLineNumber(loc)
        if self._waived(fname, line, rule):
            return
        self.violations.append(Violation(fname, line, rule, sev, message))

    def _waived(self, fname, line, rule):
        """Waiver `uvm-waive: RÈGLE` (ou chk-waive:) sur la ligne ou la ligne précédente."""
        lines = self._read(fname)
        for idx in (line - 1, line - 2):          # même ligne ou ligne précédente
            if 0 <= idx < len(lines):
                m = WAIVE.search(lines[idx])
                if m and rule in {r.strip() for r in m.group(1).replace(",", " ").split()}:
                    return True
        return False
