#!/usr/bin/env python3
"""
Side-Channel Secret Exfiltration Detector

Detects when code attempts to leak secrets indirectly via:
- Character extraction: ord(s[0]), s[i], s.encode()
- Property probing: len(s), s.startswith(), s == "guess"
- Iteration: for c in secret
- Encoding: base64.b64encode(s), s.hex()
- Indirect output: writing metadata about secrets

Works by:
1. Identifying "taint sources" (where secrets enter code)
2. Tracking taint propagation through assignments
3. Flagging operations on tainted variables that leak info

Usage:
    from side_channel_detector import scan_code
    result = scan_code(code_string)
    if result.findings:
        for f in result.findings:
            print(f)

    # Or CLI:
    python side_channel_detector.py "print(len(os.environ['SECRET']))"
"""
import ast
import os
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple


class Severity(Enum):
    CRITICAL = "CRITICAL"  # Direct character extraction
    HIGH = "HIGH"          # Property probing that reconstructs value
    MEDIUM = "MEDIUM"      # Metadata leakage (len, type checks)
    LOW = "LOW"            # Suspicious but possibly benign
    INFO = "INFO"          # Worth noting


class LeakType(Enum):
    CHAR_EXTRACTION = "char_extraction"
    ORD_BYTE = "ord_byte_value"
    ENCODING = "encoding_transform"
    PROPERTY_PROBE = "property_probe"
    COMPARISON = "comparison_leak"
    ITERATION = "iteration_over_secret"
    SLICE = "slice_extraction"
    FORMAT_STRING = "format_string_leak"
    INDIRECT_OUTPUT = "indirect_output"
    TAINT_PROPAGATION = "taint_propagation"


@dataclass
class Finding:
    line: int
    col: int
    severity: Severity
    leak_type: LeakType
    message: str
    code_snippet: str = ""
    tainted_var: str = ""

    def __str__(self):
        return (
            f"[{self.severity.value}] L{self.line}:{self.col} "
            f"({self.leak_type.value}) {self.message}"
        )


@dataclass
class ScanResult:
    findings: List[Finding] = field(default_factory=list)
    tainted_vars: Set[str] = field(default_factory=set)
    blocked: bool = False

    @property
    def max_severity(self) -> Optional[Severity]:
        if not self.findings:
            return None
        order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM,
                 Severity.LOW, Severity.INFO]
        for sev in order:
            if any(f.severity == sev for f in self.findings):
                return sev
        return None


# ─────────────────────────────────────────────────────────────────────
# Taint Sources — where secrets enter code
# ─────────────────────────────────────────────────────────────────────

# Functions/patterns that produce secret values
TAINT_SOURCE_CALLS = {
    # os.environ access
    ("os", "getenv"),
    ("os", "environ"),
    # subprocess that reads secrets
    ("subprocess", "check_output"),
    ("subprocess", "run"),
    ("subprocess", "getoutput"),
}

# Method calls on known secret-holding objects
TAINT_SOURCE_METHODS = {
    "fetchone", "fetchall", "fetchmany",  # DB results
    "read", "readline", "readlines",       # File reads
}

# Variable name patterns that suggest secrets
SECRET_NAME_PATTERNS = re.compile(
    r"(?i)(password|passwd|secret|token|api_?key|"
    r"credential|private_?key|auth|master_?key|"
    r"access_?key|conn_?str|database_?url|"
    r"redis_?url|dsn|connection_?string)",
)

# String patterns in code that access secrets
SECRET_ACCESS_PATTERNS = [
    # os.environ["KEY"] or os.environ.get("KEY")
    re.compile(r"""os\.environ\s*\["""),
    re.compile(r"""os\.environ\.get\s*\("""),
    re.compile(r"""os\.getenv\s*\("""),
    # pm2 env (subprocess)
    re.compile(r"""pm2\s+env"""),
    # docker inspect / docker exec
    re.compile(r"""docker\s+(inspect|exec)"""),
    # reading .env, credentials, key files
    re.compile(r"""open\s*\(\s*['"](.*\.(env|key|pem|token|secret|credentials))"""),
    # psycopg2/sqlite/mysql queries on config tables
    re.compile(r"""(?i)(SELECT|INSERT|UPDATE).*FROM.*(config|credential|secret|cache|token|key)"""),
]

_SEVERITY_ORDER = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}

ALL_LANGUAGES = {"python", "bash", "js", "ruby", "go"}


@dataclass
class SideChannelConfig:
    enabled: bool = True
    min_severity: Severity = Severity.MEDIUM
    mode: str = "block"                         # block | warn | log
    languages: Set[str] = field(default_factory=lambda: ALL_LANGUAGES.copy())
    extra_taint_sources: Set[str] = field(default_factory=set)

    @classmethod
    def from_env(cls) -> "SideChannelConfig":
        enabled = os.environ.get(
            "SIDE_CHANNEL_DETECTION_ENABLED", "true"
        ).lower() not in ("false", "0", "no", "off")

        min_sev_str = os.environ.get("SIDE_CHANNEL_MIN_SEVERITY", "MEDIUM").upper()
        try:
            min_severity = Severity(min_sev_str)
        except ValueError:
            min_severity = Severity.MEDIUM

        mode = os.environ.get("SIDE_CHANNEL_MODE", "block").lower()
        if mode not in ("block", "warn", "log"):
            mode = "block"

        lang_str = os.environ.get("SIDE_CHANNEL_LANGUAGES", "")
        if lang_str.strip():
            languages = {l.strip().lower() for l in lang_str.split(",") if l.strip()}
            languages &= ALL_LANGUAGES
        else:
            languages = ALL_LANGUAGES.copy()

        extra_str = os.environ.get("SIDE_CHANNEL_EXTRA_SOURCES", "")
        extra_sources = {s.strip() for s in extra_str.split(",") if s.strip()}

        return cls(
            enabled=enabled,
            min_severity=min_severity,
            mode=mode,
            languages=languages,
            extra_taint_sources=extra_sources,
        )

    def severity_meets_threshold(self, severity: Severity) -> bool:
        return _SEVERITY_ORDER.get(severity, 0) >= _SEVERITY_ORDER.get(self.min_severity, 0)


_active_config: Optional["SideChannelConfig"] = None


def get_config() -> SideChannelConfig:
    global _active_config
    if _active_config is None:
        _active_config = SideChannelConfig.from_env()
    return _active_config


def set_config(config: SideChannelConfig) -> None:
    global _active_config
    _active_config = config


def reset_config() -> None:
    global _active_config
    _active_config = None



SENSITIVE_FILE_PATTERNS = [
    re.compile(r"/proc/\d+/(environ|cmdline|maps|status)"),
    re.compile(r"/proc/self/(environ|cmdline)"),
    re.compile(r"\.(env|key|pem|token|secret|credentials|password)$"),
    re.compile(r"/(\.(ssh|gnupg|aws))/"),
    re.compile(r"/etc/(shadow|passwd|master\.passwd)"),
    re.compile(r"/(credentials|secrets?|tokens?)(\.(json|yaml|yml|toml|conf))?$"),
]

SIDE_CHANNEL_BUILTINS = {"len", "ord", "chr", "hex", "oct", "bin", "id", "hash", "type", "repr"}

SIDE_CHANNEL_METHODS = {
    "startswith", "endswith", "find", "rfind", "index", "rindex",
    "count", "encode", "decode", "hex", "bytes",
    "split", "partition", "rpartition",
    "charCodeAt", "codePointAt", "charAt",
}

ENCODING_MODULES = {
    ("base64", "b64encode"), ("base64", "b64decode"),
    ("base64", "urlsafe_b64encode"), ("base64", "encodebytes"),
    ("binascii", "hexlify"), ("binascii", "b2a_hex"),
    ("hashlib", "md5"), ("hashlib", "sha256"), ("hashlib", "sha1"),
    ("codecs", "encode"), ("codecs", "decode"),
}

OUTPUT_SINKS = {"print", "logging", "logger", "write", "send", "post"}


def _get_name(node: ast.AST) -> Optional[str]:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _get_name(node.value)
        if parent:
            return f"{parent}.{node.attr}"
        return node.attr
    return None


def _node_contains_tainted(node: ast.AST, tainted: Set[str]) -> Optional[str]:
    if isinstance(node, ast.Name) and node.id in tainted:
        return node.id
    if isinstance(node, ast.Subscript):
        return _node_contains_tainted(node.value, tainted)
    if isinstance(node, ast.Attribute):
        return _node_contains_tainted(node.value, tainted)
    if isinstance(node, ast.Call):
        for arg in node.args:
            hit = _node_contains_tainted(arg, tainted)
            if hit:
                return hit
        for kw in node.keywords:
            hit = _node_contains_tainted(kw.value, tainted)
            if hit:
                return hit
    if isinstance(node, ast.BinOp):
        return (_node_contains_tainted(node.left, tainted) or
                _node_contains_tainted(node.right, tainted))
    if isinstance(node, ast.JoinedStr):
        for val in node.values:
            if isinstance(val, ast.FormattedValue):
                hit = _node_contains_tainted(val.value, tainted)
                if hit:
                    return hit
    return None


class TaintTracker(ast.NodeVisitor):

    def __init__(self, source_lines: List[str], extra_taint_names: Optional[Set[str]] = None):
        self.tainted: Set[str] = set()
        self.findings: List[Finding] = []
        self.source_lines = source_lines
        if extra_taint_names:
            self.tainted.update(extra_taint_names)

    def _snippet(self, node: ast.AST) -> str:
        try:
            lineno = getattr(node, "lineno", None)
            if lineno is not None:
                return self.source_lines[lineno - 1].strip()
        except (IndexError, AttributeError):
            pass
        return ""

    def _add(self, node, severity, leak_type, msg, var=""):
        self.findings.append(Finding(
            line=getattr(node, "lineno", 0),
            col=getattr(node, "col_offset", 0),
            severity=severity,
            leak_type=leak_type,
            message=msg,
            code_snippet=self._snippet(node),
            tainted_var=var,
        ))

    def _is_taint_source_call(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Attribute):
            parent = _get_name(node.func.value)
            method = node.func.attr
            if parent and (parent, method) in TAINT_SOURCE_CALLS:
                return True
            if method in TAINT_SOURCE_METHODS:
                return True
        if isinstance(node.func, ast.Name):
            if node.func.id == "getenv":
                return True
            if node.func.id == "open" and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    for pat in SENSITIVE_FILE_PATTERNS:
                        if pat.search(arg0.value):
                            return True
        return False

    def _is_environ_subscript(self, node: ast.Subscript) -> bool:
        name = _get_name(node.value)
        return name in ("os.environ", "environ")

    def _value_is_tainted(self, value: ast.AST) -> bool:
        if isinstance(value, ast.Call) and self._is_taint_source_call(value):
            return True
        if isinstance(value, ast.Subscript) and self._is_environ_subscript(value):
            return True
        if _node_contains_tainted(value, self.tainted):
            return True
        if isinstance(value, ast.Attribute):
            if self._value_is_tainted(value.value):
                return True
        if isinstance(value, ast.Subscript):
            if self._value_is_tainted(value.value):
                return True
        if isinstance(value, ast.Call):
            if isinstance(value.func, ast.Attribute):
                if self._value_is_tainted(value.func.value):
                    return True
            if isinstance(value.func, ast.Name):
                for arg in value.args:
                    if self._value_is_tainted(arg):
                        return True
            for arg in value.args:
                if _node_contains_tainted(arg, self.tainted):
                    return True
        return False

    def _taint_targets(self, targets):
        for target in targets:
            if isinstance(target, ast.Name):
                self.tainted.add(target.id)
            elif isinstance(target, ast.Tuple):
                for elt in target.elts:
                    if isinstance(elt, ast.Name):
                        self.tainted.add(elt.id)

    def _check_assignment_taint(self, targets, value):
        if self._value_is_tainted(value):
            self._taint_targets(targets)

        for target in targets:
            if isinstance(target, ast.Name):
                if SECRET_NAME_PATTERNS.search(target.id):
                    self.tainted.add(target.id)

    def visit_Assign(self, node: ast.Assign):
        self._check_assignment_taint(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        if node.target and node.value:
            self._check_assignment_taint([node.target], node.value)
        self.generic_visit(node)

    def visit_For(self, node: ast.For):
        is_tainted = _node_contains_tainted(node.iter, self.tainted)
        if not is_tainted and self._value_is_tainted(node.iter):
            is_tainted = "tainted_expression"
        if is_tainted:
            self._add(node, Severity.CRITICAL, LeakType.ITERATION,
                      f"Iterating over tainted '{is_tainted}' exposes each element",
                      var=str(is_tainted))
            if isinstance(node.target, ast.Name):
                self.tainted.add(node.target.id)
            elif isinstance(node.target, ast.Tuple):
                for elt in node.target.elts:
                    if isinstance(elt, ast.Name):
                        self.tainted.add(elt.id)
        self.generic_visit(node)

    def _check_comprehension_taint(self, generators):
        for gen in generators:
            is_tainted = _node_contains_tainted(gen.iter, self.tainted)
            if not is_tainted and self._value_is_tainted(gen.iter):
                is_tainted = "tainted_expression"
            if is_tainted:
                self._add(gen, Severity.CRITICAL, LeakType.ITERATION,
                          f"Comprehension iterates over tainted '{is_tainted}'",
                          var=str(is_tainted))
                if isinstance(gen.target, ast.Name):
                    self.tainted.add(gen.target.id)
                elif isinstance(gen.target, ast.Tuple):
                    for elt in gen.target.elts:
                        if isinstance(elt, ast.Name):
                            self.tainted.add(elt.id)

    def visit_ListComp(self, node):
        self._check_comprehension_taint(node.generators)
        self.generic_visit(node)

    def visit_SetComp(self, node):
        self._check_comprehension_taint(node.generators)
        self.generic_visit(node)

    def visit_DictComp(self, node):
        self._check_comprehension_taint(node.generators)
        self.generic_visit(node)

    def visit_GeneratorExp(self, node):
        self._check_comprehension_taint(node.generators)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        var = _node_contains_tainted(node.value, self.tainted)
        if var:
            if isinstance(node.slice, ast.Constant):
                self._add(node, Severity.CRITICAL, LeakType.CHAR_EXTRACTION,
                          f"Indexing tainted '{var}' at position {node.slice.value}",
                          var=var)
            elif isinstance(node.slice, ast.Slice):
                self._add(node, Severity.CRITICAL, LeakType.SLICE,
                          f"Slicing tainted '{var}' extracts substring",
                          var=var)
            else:
                self._add(node, Severity.HIGH, LeakType.CHAR_EXTRACTION,
                          f"Dynamic indexing into tainted '{var}'",
                          var=var)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare):
        left_taint = _node_contains_tainted(node.left, self.tainted)
        if left_taint:
            self._add(node, Severity.HIGH, LeakType.COMPARISON,
                      f"Comparing tainted '{left_taint}' leaks via boolean result",
                      var=left_taint)
        for comp in node.comparators:
            comp_taint = _node_contains_tainted(comp, self.tainted)
            if comp_taint:
                self._add(node, Severity.HIGH, LeakType.COMPARISON,
                          f"Comparing against tainted '{comp_taint}'",
                          var=comp_taint)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        self._check_builtin_leak(node)
        self._check_method_leak(node)
        self._check_encoding_leak(node)
        self._check_output_sink(node)
        self.generic_visit(node)

    def _check_builtin_leak(self, node: ast.Call):
        if not isinstance(node.func, ast.Name):
            return
        fname = node.func.id
        if fname not in SIDE_CHANNEL_BUILTINS:
            return
        for arg in node.args:
            var = _node_contains_tainted(arg, self.tainted)
            if var:
                if fname == "ord":
                    self._add(node, Severity.CRITICAL, LeakType.ORD_BYTE,
                              f"ord() on tainted '{var}' exposes byte value",
                              var=var)
                elif fname == "len":
                    self._add(node, Severity.MEDIUM, LeakType.PROPERTY_PROBE,
                              f"len() on tainted '{var}' leaks secret length",
                              var=var)
                elif fname in ("hex", "oct", "bin"):
                    self._add(node, Severity.HIGH, LeakType.ENCODING,
                              f"{fname}() on tainted '{var}' encodes value",
                              var=var)
                elif fname == "repr":
                    self._add(node, Severity.CRITICAL, LeakType.PROPERTY_PROBE,
                              f"repr() on tainted '{var}' may expose full value",
                              var=var)
                elif fname == "hash":
                    self._add(node, Severity.MEDIUM, LeakType.PROPERTY_PROBE,
                              f"hash() on tainted '{var}' enables offline brute-force",
                              var=var)
                elif fname == "type":
                    self._add(node, Severity.LOW, LeakType.PROPERTY_PROBE,
                              f"type() on tainted '{var}'",
                              var=var)

    def _check_method_leak(self, node: ast.Call):
        if not isinstance(node.func, ast.Attribute):
            return
        method = node.func.attr
        var = _node_contains_tainted(node.func.value, self.tainted)
        if not var:
            return
        if method in SIDE_CHANNEL_METHODS:
            if method in ("startswith", "endswith"):
                self._add(node, Severity.HIGH, LeakType.PROPERTY_PROBE,
                          f"'{var}'.{method}() enables binary search of value",
                          var=var)
            elif method in ("find", "rfind", "index", "rindex"):
                self._add(node, Severity.HIGH, LeakType.PROPERTY_PROBE,
                          f"'{var}'.{method}() reveals character positions",
                          var=var)
            elif method == "count":
                self._add(node, Severity.MEDIUM, LeakType.PROPERTY_PROBE,
                          f"'{var}'.count() reveals character frequency",
                          var=var)
            elif method in ("encode", "decode", "hex"):
                self._add(node, Severity.HIGH, LeakType.ENCODING,
                          f"'{var}'.{method}() transforms secret encoding",
                          var=var)
            elif method in ("split", "partition", "rpartition"):
                self._add(node, Severity.MEDIUM, LeakType.PROPERTY_PROBE,
                          f"'{var}'.{method}() reveals structure",
                          var=var)

    def _check_encoding_leak(self, node: ast.Call):
        name = _get_name(node.func)
        if not name:
            return
        parts = name.rsplit(".", 1)
        if len(parts) == 2:
            mod, func = parts
            if (mod, func) in ENCODING_MODULES:
                for arg in node.args:
                    var = _node_contains_tainted(arg, self.tainted)
                    if var:
                        self._add(node, Severity.HIGH, LeakType.ENCODING,
                                  f"{name}() on tainted '{var}'",
                                  var=var)

    def _check_output_sink(self, node: ast.Call):
        fname = _get_name(node.func)
        if not fname:
            return
        is_sink = any(fname == s or fname.endswith(f".{s}") for s in OUTPUT_SINKS)
        if not is_sink:
            return
        for arg in node.args:
            var = _node_contains_tainted(arg, self.tainted)
            if var:
                self._add(node, Severity.HIGH, LeakType.INDIRECT_OUTPUT,
                          f"Outputting derived data from tainted '{var}' via {fname}()",
                          var=var)
        for kw in node.keywords:
            var = _node_contains_tainted(kw.value, self.tainted)
            if var:
                self._add(node, Severity.HIGH, LeakType.INDIRECT_OUTPUT,
                          f"Outputting derived data from tainted '{var}' via {fname}()",
                          var=var)

    def visit_JoinedStr(self, node: ast.JoinedStr):
        for val in node.values:
            if isinstance(val, ast.FormattedValue):
                var = _node_contains_tainted(val.value, self.tainted)
                if var:
                    self._add(node, Severity.HIGH, LeakType.FORMAT_STRING,
                              f"f-string interpolates tainted '{var}'",
                              var=var)
        self.generic_visit(node)


BASH_SIDE_CHANNEL_PATTERNS = [
    (re.compile(r"""\$\w+\s*\|\s*cut\s+-c"""), Severity.CRITICAL,
     "Extracting characters from variable with cut -c"),
    (re.compile(r"""echo\s+.*\$\w+.*\|\s*wc\s+-c"""), Severity.MEDIUM,
     "Measuring secret length with wc -c"),
    (re.compile(r"""expr\s+substr\s+\$"""), Severity.CRITICAL,
     "Extracting substring from variable with expr substr"),
    (re.compile(r"""\$\{(\w+):(\d+):(\d+)\}"""), Severity.CRITICAL,
     "Bash substring extraction ${var:offset:length}"),
    (re.compile(r"""\$\{#\w+\}"""), Severity.MEDIUM,
     "Getting variable length with ${#var}"),
    (re.compile(r"""printf\s+['"]*%d.*'"\$"""), Severity.HIGH,
     "printf %d on secret character (ASCII value)"),
    (re.compile(r"""xxd|od\s+-[AaxX]|hexdump"""), Severity.HIGH,
     "Hex dump of data (potential secret encoding)"),
    (re.compile(r"""base64(\s*(<<<|<\(|\|)|\s*$)"""), Severity.HIGH,
     "Base64 encoding (potential secret exfiltration)"),
    (re.compile(r"""\[\[\s*\$\w+\s*==\s*"""), Severity.HIGH,
     "String comparison against variable (brute-force probe)"),
    (re.compile(r"""curl.*\$\w+|wget.*\$\w+"""), Severity.CRITICAL,
     "Sending variable content via HTTP (exfiltration)"),
]

MULTILANG_SIDE_CHANNEL_PATTERNS = [
    (re.compile(r"""\.charCodeAt\s*\("""), Severity.CRITICAL, "js",
     "charCodeAt() extracts character code"),
    (re.compile(r"""\.charAt\s*\("""), Severity.HIGH, "js",
     "charAt() extracts single character"),
    (re.compile(r"""\.codePointAt\s*\("""), Severity.CRITICAL, "js",
     "codePointAt() extracts character code"),
    (re.compile(r"""\.substring\s*\("""), Severity.HIGH, "js",
     "substring() extracts partial value"),
    (re.compile(r"""\.bytes\s*\["""), Severity.CRITICAL, "ruby/go",
     "Byte-level access to string"),
    (re.compile(r"""\.each_byte"""), Severity.CRITICAL, "ruby",
     "Iterating bytes of string"),
    (re.compile(r"""\.each_char"""), Severity.CRITICAL, "ruby",
     "Iterating characters of string"),
    (re.compile(r"""\.unpack\s*\("""), Severity.HIGH, "ruby",
     "Unpacking string to numeric values"),
    (re.compile(r"""strings\.Contains\s*\("""), Severity.HIGH, "go",
     "String containment check"),
    (re.compile(r"""utf8\.DecodeRune"""), Severity.CRITICAL, "go",
     "Decoding individual rune from string"),
    (re.compile(r"""fmt\.Println\s*\(.*\[\d+\]"""), Severity.CRITICAL, "go",
     "Printing indexed byte of string"),
]


_EMBEDDED_PYTHON_RE = re.compile(r"""python[23]?\s+-c\s+["'](.+?)["']"""  , re.DOTALL)


def _scan_bash(code: str) -> List[Finding]:
    findings = []
    for i, line in enumerate(code.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for pattern, severity, message in BASH_SIDE_CHANNEL_PATTERNS:
            if pattern.search(stripped):
                findings.append(Finding(
                    line=i, col=0, severity=severity,
                    leak_type=LeakType.CHAR_EXTRACTION,
                    message=message, code_snippet=stripped,
                ))
        for m in _EMBEDDED_PYTHON_RE.finditer(stripped):
            embedded = m.group(1)
            try:
                tree = ast.parse(embedded)
                tracker = TaintTracker(embedded.splitlines())
                tracker.visit(tree)
                for f in tracker.findings:
                    f.message = f"[embedded python] {f.message}"
                    f.line = i
                findings.extend(tracker.findings)
            except SyntaxError:
                pass
    return findings


def _scan_multilang(code: str, enabled_langs: Optional[Set[str]] = None) -> List[Finding]:
    findings = []
    for i, line in enumerate(code.splitlines(), 1):
        stripped = line.strip()
        for pattern, severity, lang, message in MULTILANG_SIDE_CHANNEL_PATTERNS:
            if enabled_langs and not any(l in lang for l in enabled_langs):
                continue
            if pattern.search(stripped):
                findings.append(Finding(
                    line=i, col=0, severity=severity,
                    leak_type=LeakType.CHAR_EXTRACTION,
                    message=f"[{lang}] {message}",
                    code_snippet=stripped,
                ))
    return findings


def _detect_language(code: str) -> str:
    if any(kw in code for kw in ("import ", "def ", "os.environ", "print(")):
        return "python"
    if any(kw in code for kw in ("#!/bin/bash", "#!/bin/sh", "echo ", "export ")):
        return "bash"
    return "unknown"


def _filter_findings(findings: List[Finding], config: SideChannelConfig) -> List[Finding]:
    return [f for f in findings if config.severity_meets_threshold(f.severity)]


def _multilang_languages(config: SideChannelConfig) -> Set[str]:
    return config.languages - {"python", "bash"}


def scan_code(
    code: str,
    language: str = "auto",
    config: Optional[SideChannelConfig] = None,
) -> ScanResult:
    if config is None:
        config = get_config()

    if not config.enabled:
        return ScanResult()

    result = ScanResult()

    if language == "auto":
        language = _detect_language(code)

    if language == "python" and "python" in config.languages:
        try:
            tree = ast.parse(code)
            tracker = TaintTracker(code.splitlines(), config.extra_taint_sources)
            tracker.visit(tree)
            result.findings.extend(tracker.findings)
            result.tainted_vars = tracker.tainted
        except SyntaxError:
            pass

    if language == "bash" and "bash" in config.languages:
        result.findings.extend(_scan_bash(code))

    enabled_ml = _multilang_languages(config)
    if enabled_ml:
        result.findings.extend(_scan_multilang(code, enabled_ml))

    result.findings = _filter_findings(result.findings, config)

    should_block = (
        config.mode == "block"
        and result.max_severity in (Severity.CRITICAL, Severity.HIGH)
    )
    result.blocked = should_block

    return result


def scan_bash_command(
    cmd: str,
    config: Optional[SideChannelConfig] = None,
) -> ScanResult:
    if config is None:
        config = get_config()

    if not config.enabled:
        return ScanResult()

    result = ScanResult()

    if "bash" in config.languages:
        result.findings.extend(_scan_bash(cmd))

    enabled_ml = _multilang_languages(config)
    if enabled_ml:
        result.findings.extend(_scan_multilang(cmd, enabled_ml))

    result.findings = _filter_findings(result.findings, config)

    should_block = (
        config.mode == "block"
        and result.max_severity in (Severity.CRITICAL, Severity.HIGH)
    )
    result.blocked = should_block

    return result


def format_report(result: ScanResult) -> str:
    if not result.findings:
        return "No side-channel exfiltration patterns detected."

    lines = []
    lines.append("=" * 60)
    lines.append("SIDE-CHANNEL EXFILTRATION SCAN REPORT")
    lines.append("=" * 60)
    lines.append(f"Findings: {len(result.findings)}")
    lines.append(f"Max Severity: {result.max_severity.value if result.max_severity else 'NONE'}")
    lines.append(f"Verdict: {'BLOCK' if result.blocked else 'WARN'}")
    if result.tainted_vars:
        lines.append(f"Tainted Variables: {', '.join(sorted(result.tainted_vars))}")
    lines.append("-" * 60)

    for i, f in enumerate(result.findings, 1):
        lines.append(f"\n[{i}] {f}")
        if f.code_snippet:
            lines.append(f"    Code: {f.code_snippet}")

    lines.append("\n" + "=" * 60)
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        code_input = sys.argv[1]
        if code_input.endswith(".py"):
            with open(code_input) as fh:
                code_input = fh.read()
        result = scan_code(code_input)
        print(format_report(result))
        sys.exit(1 if result.blocked else 0)
    else:
        print("Usage: python side_channel_detector.py '<code>' | <file.py>")
        sys.exit(2)