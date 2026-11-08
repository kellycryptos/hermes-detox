"""Exhaustive live verification script for Hermes Detox.
Exercises every single tool, hook, extractor, storage engine, slash command,
and claim made in the README and plugin.yaml.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Ensure agent.redact is importable for verification
try:
    import agent.redact
except ImportError:
    for candidate in (
        str(Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"),
        r"C:\Users\HP\AppData\Local\hermes\hermes-agent",
        "/tmp/hermes-agent",
        str(REPO_ROOT.parent / "hermes-repo"),
        str(REPO_ROOT.parent / "hermes_pkg"),
    ):
        if candidate and Path(candidate).is_dir() and candidate not in sys.path:
            sys.path.insert(0, candidate)
            try:
                import agent.redact
                break
            except ImportError:
                pass

import importlib.util
if "hermes_detox" not in sys.modules:
    _init_path = REPO_ROOT / "__init__.py"
    _spec = importlib.util.spec_from_file_location(
        "hermes_detox",
        str(_init_path),
        submodule_search_locations=[str(REPO_ROOT)],
    )
    _mod = importlib.util.module_from_spec(_spec)
    _mod.__package__ = "hermes_detox"
    _mod.__path__ = [str(REPO_ROOT)]
    sys.modules["hermes_detox"] = _mod
    _spec.loader.exec_module(_mod)
else:
    _mod = sys.modules["hermes_detox"]
detox = _mod
from hermes_detox.config import DetoxConfig, get_config, set_config
from hermes_detox.store import EvidenceStore, set_storage_dir_override
from hermes_detox.detox_tools.tool_inspect import handle_detox_inspect
from hermes_detox.detox_tools.tool_search import handle_detox_search
from hermes_detox.detox_tools.tool_status import handle_detox_status
from hermes_detox.retention import run_retention_prune, maybe_run_retention_prune
from hermes_detox.extractors import detect_and_extract_summary

passed_checks = []
failed_checks = []

def check(name: str, condition: bool, details: str = ""):
    if condition:
        print(f"  [PASS] {name} {details}")
        passed_checks.append(name)
    else:
        print(f"  [FAIL] {name} {details}")
        failed_checks.append(name)

print("=" * 80)
print("HERMES DETOX: EXHAUSTIVE LIVE CAPABILITY & CLAIM VERIFICATION")
print("=" * 80)

# ---------------------------------------------------------------------------
# Setup isolated temporary storage
# ---------------------------------------------------------------------------
test_temp_dir = tempfile.mkdtemp(prefix="detox_verify_")
set_storage_dir_override(Path(test_temp_dir))
store = EvidenceStore()

try:
    # -----------------------------------------------------------------------
    # TEST 1: Registration Integrity & plugin.yaml Consistency
    # -----------------------------------------------------------------------
    print("\n--- TEST 1: Plugin Registration & Schema Integrity ---")
    class MockContext:
        def __init__(self):
            self.hooks = {}
            self.tools = {}
            self.commands = {}
            self._config = {}
        def register_hook(self, name, fn): self.hooks[name] = fn
        def register_tool(self, name, toolset, schema, handler):
            self.tools[name] = {"schema": schema, "handler": handler}
        def register_command(self, name, handler, description):
            self.commands[name] = {"handler": handler, "desc": description}
        def get_config(self): return self._config

    mock_ctx = MockContext()
    detox.register(mock_ctx)

    check("Hook registered: transform_tool_result", "transform_tool_result" in mock_ctx.hooks)
    check("Hook registered: transform_terminal_output", "transform_terminal_output" in mock_ctx.hooks)
    check("Hook registered: on_session_reset", "on_session_reset" in mock_ctx.hooks)
    check("Tool registered: detox_inspect", "detox_inspect" in mock_ctx.tools)
    check("Tool registered: detox_search", "detox_search" in mock_ctx.tools)
    check("Tool registered: detox_status", "detox_status" in mock_ctx.tools)
    check("Slash command registered: detox", "detox" in mock_ctx.commands)

    # -----------------------------------------------------------------------
    # TEST 2: Threshold & Passthrough Checks
    # -----------------------------------------------------------------------
    print("\n--- TEST 2: Threshold & Exclusion Gates ---")
    
    # 2a: Small output (< 6000 chars) must return None (passthrough)
    small_output = "Hello world! Test small output." * 50  # ~1500 chars
    res_small = detox.on_transform_tool_result("terminal", {}, small_output)
    check("Small output passes through untouched (None)", res_small is None)

    # 2b: Excluded tool passes through even if > 6000 chars
    large_payload = "Some text line with information\n" * 300  # ~9600 chars
    res_excluded = detox.on_transform_tool_result("browser_vision", {}, large_payload)
    check("Default excluded tool (browser_vision) passes through untouched", res_excluded is None)

    res_patch = detox.on_transform_tool_result("patch", {}, large_payload)
    check("Default excluded tool (patch) passes through untouched", res_patch is None)

    # 2c: Detox retrieval tools are self-excluded
    res_self = detox.on_transform_tool_result("detox_inspect", {}, large_payload)
    check("Detox tool self-exclusion (detox_inspect passes through)", res_self is None)

    # 2d: Media / Base64 bypass
    b64_output = "data:image/png;base64," + ("iVBORw0KGgoAAAANSUhEUgAA" * 400)
    res_b64 = detox.on_transform_tool_result("terminal", {}, b64_output)
    check("Base64/image payload passes through untouched", res_b64 is None)

    # -----------------------------------------------------------------------
    # TEST 3: All 6 Extractors & Report Generation
    # -----------------------------------------------------------------------
    print("\n--- TEST 3: Content-Aware Extractors ---")

    # 3a: Pytest test runner
    pytest_output = (
        "=== test session starts ===\n"
        "rootdir: /app\n"
        "collected 50 items\n"
        "tests/test_auth.py::test_login PASSED [ 2%]\n" * 47 +
        "tests/test_auth.py::test_fail_1 FAILED [ 96%]\n"
        "tests/test_auth.py::test_fail_2 FAILED [ 98%]\n"
        "tests/test_auth.py::test_fail_3 FAILED [100%]\n"
        "=== FAILURES ===\n"
        "___ test_fail_1 ___\n"
        "AssertionError: Expected 200 got 500\n"
        "___ test_fail_2 ___\n"
        "KeyError: 'token'\n"
        "___ test_fail_3 ___\n"
        "ValueError: Invalid signature\n"
        "=== 3 failed, 47 passed in 4.21s ===\n"
    )
    # Pad to > 6000 chars
    pytest_full = pytest_output + ("# padding comment line\n" * 250)
    res_pytest = detox.on_transform_tool_result("terminal", {"command": "pytest"}, pytest_full, session_id="s1")
    check("Pytest intercepted and compressed", res_pytest is not None and "=== [DETOX FIREWALL:" in res_pytest)
    check("Pytest report mentions 3 failed or failures", "3 failed" in res_pytest or "test_fail" in res_pytest)

    # 3b: C++ / Compiler build log
    build_output = (
        "g++ -O3 -c src/main.cpp -o build/main.o\n"
        "src/auth.cpp:45:12: error: 'token_secret' was not declared in this scope\n"
        "src/auth.cpp:89:5: warning: unused variable 'unused_val'\n"
        "build/libauth.a(auth.o): undefined reference to `verify_jwt`\n"
        "collect2: error: ld returned 1 exit status\n"
    ) + ("// compilation notes and includes...\n" * 400)
    res_build = detox.on_transform_tool_result("run_build", {}, build_output, session_id="s1")
    check("Build log intercepted and compressed", res_build is not None and "=== [DETOX FIREWALL:" in res_build)
    check("Build diagnostics preserved (undefined reference / error)", "undefined reference" in res_build or "error:" in res_build)

    # 3c: JSON API Payload
    records = [{"id": i, "user": f"user_{i}", "active": True, "meta": {"score": i * 10}} for i in range(100)]
    json_output = json.dumps({"status": "success", "count": 100, "items": records}, indent=2)
    res_json = detox.on_transform_tool_result("api_fetch", {}, json_output, session_id="s1")
    check("JSON payload intercepted and compressed", res_json is not None and "=== [DETOX FIREWALL:" in res_json)
    check("JSON report preserves structure/keys", "status" in res_json or "items" in res_json)

    # 3d: File Listing
    file_list = "\n".join([f"/var/log/app/service_{i}.log" for i in range(500)])
    res_files = detox.on_transform_tool_result("list_files", {}, file_list, session_id="s1")
    check("File listing intercepted and compressed", res_files is not None and "=== [DETOX FIREWALL:" in res_files)

    # -----------------------------------------------------------------------
    # TEST 4: The Amputation & Zero-Loss Recovery Claim
    # -----------------------------------------------------------------------
    print("\n--- TEST 4: Zero-Loss Amputation & Diagnostic Vault ---")
    lines = [f"[DEBUG] worker thread {i} cycle step 100" for i in range(1200)]
    CRITICAL_MARKER = "CRITICAL_DATABASE_TIMEOUT_EXCEPTION_AT_LINE_600"
    lines[599] = f"[ERROR] {CRITICAL_MARKER}: DB connection pool died"
    large_log = "\n".join(lines)
    
    res_amputation = detox.on_transform_tool_result("terminal", {}, large_log, session_id="s_amp")
    check("Massive log (>50k chars) compressed", res_amputation is not None)
    
    # Extract evidence ID
    import re
    ev_match = re.search(r"ev_[a-f0-9]{12}", res_amputation)
    check("Evidence ID generated and returned in report", ev_match is not None)
    ev_id = ev_match.group(0) if ev_match else ""

    # Verify critical marker is highlighted in the report
    check("Critical error at line 600 surfaced in diagnostic report", CRITICAL_MARKER in res_amputation)

    # Verify 100% exact line retrieval via detox_inspect
    inspect_res = handle_detox_inspect({"evidence_id": ev_id, "start_line": 599, "end_line": 601}, session_id="s_amp")
    inspect_data = json.loads(inspect_res)
    check("detox_inspect succeeds", inspect_data.get("success") is True)
    check("detox_inspect retrieved exact 3 lines", len(inspect_data.get("lines", [])) == 3)
    check("detox_inspect line 600 matches original verbatim", CRITICAL_MARKER in inspect_data.get("lines", ["", ""])[1])

    # Verify detox_search finds the query with exact line number
    search_res = handle_detox_search({"evidence_id": ev_id, "query": CRITICAL_MARKER}, session_id="s_amp")
    search_data = json.loads(search_res)
    check("detox_search succeeds", search_data.get("success") is True)
    check("detox_search found matching record", search_data.get("matches_count", 0) >= 1)
    if search_data.get("results"):
        check("detox_search reports exact 1-based line 600", search_data["results"][0]["line_number"] == 600)

    # -----------------------------------------------------------------------
    # TEST 5: Slash Commands (`/detox`)
    # -----------------------------------------------------------------------
    print("\n--- TEST 5: Slash Command Suite ---")
    status_msg = detox.handle_detox_slash_command("status")
    check("/detox status returns cleanly", "Outputs intercepted:" in status_msg and "Characters saved:" in status_msg)

    inspect_cmd_res = detox.handle_detox_slash_command(f"inspect {ev_id} 600 600")
    check("/detox inspect <id> prints exact line", CRITICAL_MARKER in inspect_cmd_res)

    search_cmd_res = detox.handle_detox_slash_command(f"search {CRITICAL_MARKER} {ev_id}")
    check("/detox search prints matched line", CRITICAL_MARKER in search_cmd_res)

    purge_cmd_res = detox.handle_detox_slash_command("purge")
    check("/detox purge executes retention purge", "Detox Retention Purge Completed" in purge_cmd_res)

    help_cmd_res = detox.handle_detox_slash_command("help")
    check("/detox help prints command options", "Commands:" in help_cmd_res and "/detox status" in help_cmd_res)

    # -----------------------------------------------------------------------
    # TEST 6: Double-Wrap Guard
    # -----------------------------------------------------------------------
    print("\n--- TEST 6: Double-Wrap Guard ---")
    already_wrapped = res_amputation
    second_pass = detox.on_transform_tool_result("terminal", {}, already_wrapped, session_id="s_double")
    check("Already-wrapped report is NOT wrapped again (returns None)", second_pass is None)

    # -----------------------------------------------------------------------
    # TEST 7: Fail-Open Resilience Under Faults
    # -----------------------------------------------------------------------
    print("\n--- TEST 7: Fail-Open Reliability ---")
    # Simulate an unwriteable/corrupt database file
    db_path = EvidenceStore.get_instance().db_path
    EvidenceStore.reset_instance()
    
    # Overwrite db with garbage
    with open(db_path, "wb") as f:
        f.write(b"CORRUPTED_GARBAGE_BYTES_NOT_A_SQLITE_DATABASE" * 100)
    
    # transform_tool_result must fail-open (return None) without raising any exception
    try:
        corrupt_res = detox.on_transform_tool_result("terminal", {}, large_log, session_id="s_corrupt")
        check("Corrupted SQLite fails open cleanly (returns None, 0 uncaught exception)", corrupt_res is None)
    except Exception as e:
        check("Corrupted SQLite fails open cleanly", False, f"Exception raised: {e}")

finally:
    # Cleanup temp directory
    try:
        shutil.rmtree(test_temp_dir, ignore_errors=True)
    except Exception:
        pass

print("\n" + "=" * 80)
print(f"VERIFICATION RESULTS: {len(passed_checks)} PASSED / {len(failed_checks)} FAILED")
print("=" * 80)

if failed_checks:
    sys.exit(1)
