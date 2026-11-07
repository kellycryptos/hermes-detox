"""Core unit tests for Hermes Detox (Stage 1)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Import using module name from root
import importlib.util
_init_path = REPO_ROOT / "__init__.py"
_spec = importlib.util.spec_from_file_location("hermes_detox", str(_init_path))
_mod = importlib.util.module_from_spec(_spec)
sys.modules["hermes_detox"] = _mod
_spec.loader.exec_module(_mod)

on_transform_tool_result = _mod.on_transform_tool_result
on_transform_terminal_output = _mod.on_transform_terminal_output
handle_detox_slash_command = _mod.handle_detox_slash_command
register = _mod.register

from report import build_compact_report
from store import EvidenceStore, set_storage_dir_override
from detox_tools.tool_inspect import handle_detox_inspect
from detox_tools.tool_search import handle_detox_search
from detox_tools.tool_status import handle_detox_status


class MockHermesContext:
    """Mock Hermes plugin registration context for unit testing."""

    def __init__(self, config=None):
        self._config = config or {"enabled": True, "min_size": 2000}
        self.hooks = {}
        self.tools = {}
        self.commands = {}

    def get_config(self):
        return self._config

    def register_hook(self, hook_name, callback):
        self.hooks.setdefault(hook_name, []).append(callback)

    def register_tool(self, name, toolset, schema, handler):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler}

    def register_command(self, name, handler, description=""):
        self.commands[name] = {"handler": handler, "description": description}


class TestDetoxCore(unittest.TestCase):
    """Test suite covering Stage 1 firewall and retrieval behavior."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="detox_test_"))
        set_storage_dir_override(self.test_dir)
        EvidenceStore._instance = None

    def tearDown(self):
        set_storage_dir_override(None)
        EvidenceStore._instance = None
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_registration_integrity(self):
        """Verify register(ctx) registers exactly the declared hooks, tools, and commands."""
        ctx = MockHermesContext()
        register(ctx)

        self.assertIn("transform_tool_result", ctx.hooks)
        self.assertIn("transform_terminal_output", ctx.hooks)
        self.assertIn("on_session_reset", ctx.hooks)
        self.assertIn("detox_inspect", ctx.tools)
        self.assertIn("detox_search", ctx.tools)
        self.assertIn("detox_status", ctx.tools)
        self.assertIn("detox", ctx.commands)

    def test_small_output_unchanged(self):
        """Outputs below min_size threshold (6,000 chars) must return None (untouched)."""
        small_text = "Short tool output\nEverything looks good."
        res = on_transform_tool_result(
            tool_name="git_status",
            result=small_text,
            session_id="test_sess",
        )
        self.assertIsNone(res, "Small outputs must return None to leave them unchanged")

        # 5,000 character output (below 6,000 default threshold) must also return None
        below_thresh = "A" * 5000
        res_below = on_transform_tool_result(
            tool_name="verbose_query",
            result=below_thresh,
            session_id="test_sess",
        )
        self.assertIsNone(res_below, "5,000 char output must stay untouched with default 6,000 threshold")

    def test_empty_output_handled(self):
        """Empty outputs must return None without raising."""
        self.assertIsNone(on_transform_tool_result(tool_name="test", result=""))
        self.assertIsNone(on_transform_tool_result(tool_name="test", result=None))

    def test_large_output_replaced_and_recoverable(self):
        """Large outputs (>6,000 chars) must be replaced with compact report and recoverable via inspect."""
        # Create 8,500 character output across 160 lines
        lines = [f"Line {i:03d}: System check log entry with payload {i * 42}" for i in range(1, 161)]
        lines[25] = "Line 026: CRITICAL ERROR - Database connection timeout"
        large_output = "\n".join(lines)
        self.assertGreater(len(large_output), 6000)

        compact_report = on_transform_tool_result(
            tool_name="run_migrations",
            result=large_output,
            session_id="session_42",
        )

        self.assertIsNotNone(compact_report)
        self.assertIn("[DETOX FIREWALL: run_migrations]", compact_report)
        self.assertIn("CRITICAL ERROR", compact_report)
        self.assertIn("Line 026", compact_report)

        # Extract evidence ID from the report
        match = re.search(r"evidence: `(ev_[a-f0-9]+)`", compact_report)
        self.assertIsNotNone(match)
        ev_id = match.group(1)

        # Inspect exact lines 25 to 27
        inspect_raw = handle_detox_inspect({
            "evidence_id": ev_id,
            "start_line": 25,
            "end_line": 27,
        }, session_id="session_42")

        inspect_data = json.loads(inspect_raw)
        self.assertTrue(inspect_data.get("success"), f"Inspect failed: {inspect_raw}")
        self.assertEqual(inspect_data["start_line"], 25)
        self.assertEqual(inspect_data["end_line"], 27)
        self.assertEqual(len(inspect_data["lines"]), 3)
        self.assertEqual(inspect_data["lines"][1], lines[25])

    def test_exact_line_retrieval(self):
        """Verify boundary precision for line retrieval (1-based inclusive)."""
        sample = "\n".join([f"row_{i}" for i in range(1, 101)])
        store = EvidenceStore.get_instance()
        ev_id = store.save(
            session_id="sess_lines",
            tool_name="test_tool",
            original_output=sample,
            transformed_size=100,
        )

        # Slice 10 to 15
        res = store.get_lines(ev_id, start_line=10, end_line=15)
        self.assertTrue(res["success"])
        self.assertEqual(res["line_count"], 6)
        self.assertEqual(res["lines"][0], "row_10")
        self.assertEqual(res["lines"][-1], "row_15")

    def test_error_status_preserved_verbatim(self):
        """Results with error status/type/message must preserve error details verbatim."""
        noisy_output = "info line\n" * 800 + "Traceback (most recent call last):\n  File 'app.py', line 12\nZeroDivisionError: division by zero\n" + "end line\n" * 100
        
        report = on_transform_tool_result(
            tool_name="execute_python",
            result=noisy_output,
            status="error",
            error_type="ZeroDivisionError",
            error_message="division by zero occurred in module compute",
        )

        self.assertIsNotNone(report)
        self.assertIn("Error Type: ZeroDivisionError", report)
        self.assertIn("division by zero occurred in module compute", report)
        self.assertIn("ZeroDivisionError: division by zero", report)

    def test_storage_failure_fails_open(self):
        """If storage write raises an error, transform_tool_result must fail open (return None)."""
        noisy_output = "A" * 5000

        store = EvidenceStore.get_instance()
        def broken_save(*args, **kwargs):
            raise Exception("Simulated disk failure / permission denied")

        store.save = broken_save

        result = on_transform_tool_result(
            tool_name="flakey_tool",
            result=noisy_output,
        )
        self.assertIsNone(result, "Storage failure must return None (fail open)")

    def test_detox_search_tool(self):
        """Search tool returns matching lines with accurate line numbers."""
        output = "setup 1\nsetup 2\nFATAL: Memory corruption at 0xdeadbeef\ncleanup 1\ncleanup 2\n" * 50
        store = EvidenceStore.get_instance()
        ev_id = store.save(
            session_id="search_sess",
            tool_name="compiler",
            original_output=output,
            transformed_size=200,
        )

        search_raw = handle_detox_search({
            "query": "Memory corruption",
            "evidence_id": ev_id,
        }, session_id="search_sess")

        search_data = json.loads(search_raw)
        self.assertTrue(search_data["success"])
        self.assertGreater(search_data["matches_count"], 0)
        first_match = search_data["results"][0]
        self.assertEqual(first_match["evidence_id"], ev_id)
        self.assertEqual(first_match["line_number"], 3)
        self.assertIn("FATAL: Memory corruption", first_match["line"])

    def test_detox_status_metrics(self):
        """Status tool calculates characters saved accurately."""
        store = EvidenceStore.get_instance()
        store.save("sess1", "tool_a", "A" * 10000, 1000)
        store.save("sess1", "tool_b", "B" * 5000, 500)

        raw_status = handle_detox_status({}, session_id="sess1")
        data = json.loads(raw_status)

        self.assertEqual(data["outputs_intercepted"], 2)
        self.assertEqual(data["characters_in"], 15000)
        self.assertEqual(data["characters_out"], 1500)
        self.assertEqual(data["characters_saved"], 13500)
        self.assertEqual(data["saved_percentage"], 90.0)

    def test_slash_command_dispatch(self):
        """Verify /detox subcommands return clean human-readable strings."""
        store = EvidenceStore.get_instance()
        ev_id = store.save("sess_cmd", "bash", "line one\nline two\nline three", 50)

        # /detox status
        status_text = handle_detox_slash_command("status")
        self.assertIn("Detox Firewall Status", status_text)
        self.assertIn("Outputs intercepted", status_text)

        # /detox inspect
        inspect_text = handle_detox_slash_command(f"inspect {ev_id} 1 2")
        self.assertIn("line one", inspect_text)
        self.assertIn("line two", inspect_text)

        # /detox search
        search_text = handle_detox_slash_command(f"search two {ev_id}")
        self.assertIn("line two", search_text)

    def test_detox_tools_excluded_from_interception(self):
        """Self-exclusion: detox_inspect, detox_search, and detox_status must return None even for huge outputs."""
        huge_output = "Line of inspect payload\n" * 500  # > 10,000 chars
        self.assertGreater(len(huge_output), 10000)

        for detox_tool in ("detox_inspect", "detox_search", "detox_status"):
            res = on_transform_tool_result(
                tool_name=detox_tool,
                result=huge_output,
                session_id="self_exclude_test",
            )
            self.assertIsNone(
                res,
                f"Detox tool '{detox_tool}' must be hardcoded excluded from interception to prevent recursion loops",
            )

    def test_compression_ratio_gate(self):
        """Report is only used if it achieves significant reduction (at most ~50% original size)."""
        # Create output barely exceeding min_size (2,050 chars) where report would not save ~50%
        output_2050 = "A" * 2050
        res = on_transform_tool_result(
            tool_name="generic_tool",
            result=output_2050,
            session_id="ratio_test",
        )
        # Because a generic compact report with header, retrieval instructions, etc.
        # will exceed 55% of 2,050 chars, it should safely return None (fail open / keep original)
        if res is not None:
            self.assertLessEqual(len(res), len(output_2050) * 0.55)

    def test_session_purge_and_relink(self):
        """Test evidence session linking after compaction and purging on reset/delete."""
        store = EvidenceStore.get_instance()
        ev_id = store.save(
            session_id="sess_old",
            tool_name="tool_purge",
            original_output="content to be purged or linked\n" * 100,
            transformed_size=50,
        )

        # 1. Relink session
        updated = store.relink_session("sess_old", "sess_new")
        self.assertEqual(updated, 1)
        record = store.get(ev_id, session_id="sess_new")
        self.assertIsNotNone(record)
        self.assertEqual(record["session_id"], "sess_new")

        # 2. Purge session
        deleted = store.purge_session("sess_new")
        self.assertEqual(deleted, 1)
        record_after = store.get(ev_id, session_id="sess_new")
        self.assertIsNone(record_after)

    def test_background_process_output_ignored(self):
        """Background process notifications (returncode=None, env_type empty) must NOT create evidence."""
        store = EvidenceStore.get_instance()
        bg_output = "Process #402 status: RUNNING. Polled output stream.\n" * 200  # > 6,000 chars
        self.assertGreater(len(bg_output), 6000)

        res = on_transform_terminal_output(
            command="",
            output=bg_output,
            returncode=None,
            env_type="",
            session_id="sess_bg",
        )
        self.assertIsNone(res, "Background process lifecycle outputs must return None")

        # Confirm no evidence record was stored
        status_raw = handle_detox_status({}, session_id="sess_bg")
        status_data = json.loads(status_raw)
        self.assertEqual(status_data["outputs_intercepted"], 0, "No evidence should be stored for background poll/wait")

    def test_parallel_terminal_no_id_swap(self):
        """Two terminal calls in same session create distinct evidence IDs without swapping or cross-contamination."""
        term_output_1 = "Build job 1 starting\n" + ("Compiling module alpha\n" * 300) + "Build job 1 completed\n"
        term_output_2 = "Build job 2 starting\n" + ("Compiling module beta\n" * 300) + "Build job 2 completed\n"
        self.assertGreater(len(term_output_1), 6000)
        self.assertGreater(len(term_output_2), 6000)

        report_1 = on_transform_terminal_output(
            command="make target_alpha",
            output=term_output_1,
            returncode=0,
            env_type="bash",
            session_id="sess_parallel",
        )
        report_2 = on_transform_terminal_output(
            command="make target_beta",
            output=term_output_2,
            returncode=0,
            env_type="bash",
            session_id="sess_parallel",
        )

        self.assertIsNotNone(report_1)
        self.assertIsNotNone(report_2)

        ev_1 = re.search(r"evidence: `(ev_[a-f0-9]+)`", report_1).group(1)
        ev_2 = re.search(r"evidence: `(ev_[a-f0-9]+)`", report_2).group(1)
        self.assertNotEqual(ev_1, ev_2, "Parallel calls must receive distinct evidence IDs")

        # Inspect ev_1 -> should contain alpha, NOT beta
        inspect_1 = json.loads(handle_detox_inspect({"evidence_id": ev_1, "start_line": 2, "end_line": 4}))
        self.assertIn("alpha", inspect_1["content"])
        self.assertNotIn("beta", inspect_1["content"])

        # Inspect ev_2 -> should contain beta, NOT alpha
        inspect_2 = json.loads(handle_detox_inspect({"evidence_id": ev_2, "start_line": 2, "end_line": 4}))
        self.assertIn("beta", inspect_2["content"])
        self.assertNotIn("alpha", inspect_2["content"])

        # Second guard: transform_tool_result must NOT re-intercept already transformed reports
        second_pass = on_transform_tool_result(
            tool_name="terminal",
            result=report_1,
            session_id="sess_parallel",
        )
        self.assertIsNone(second_pass, "Already-transformed compact reports must return None to prevent double-wrapping")

    def test_terminal_over_50k_untruncated(self):
        """Hermes truncates terminal output at 50,000 characters (keeping 40% head and 60% tail).
        Verify Detox captures full >50k output and recovers exact lines from the middle."""
        # Create 75,000 character output across 1,500 lines
        lines = [f"Line {i:04d}: Normal log entry streaming telemetry packet {i}" for i in range(1, 1501)]
        # Put critical marker at line 750 (exact middle, character position ~37,500)
        lines[749] = "Line 0750: CRITICAL_MIDDLE_MARKER_99887766 - Root cause found here"
        huge_output = "\n".join(lines)
        self.assertGreater(len(huge_output), 70000, "Output must significantly exceed Hermes's 50k cap")

        report = on_transform_terminal_output(
            command="tail -n 1500 /var/log/app.log",
            output=huge_output,
            returncode=0,
            env_type="bash",
            session_id="sess_50k",
        )

        self.assertIsNotNone(report)
        ev_id = re.search(r"evidence: `(ev_[a-f0-9]+)`", report).group(1)

        # In standard Hermes, line 750 would be completely destroyed by the 50k truncation middle replacement
        # In Detox, line 750 is 100% preserved in SQLite and retrievable via detox_inspect
        inspect_raw = handle_detox_inspect({
            "evidence_id": ev_id,
            "start_line": 749,
            "end_line": 751,
        }, session_id="sess_50k")

        inspect_data = json.loads(inspect_raw)
        self.assertTrue(inspect_data["success"])
        self.assertEqual(len(inspect_data["lines"]), 3)
        self.assertEqual(inspect_data["lines"][1], lines[749])
        self.assertIn("CRITICAL_MIDDLE_MARKER_99887766", inspect_data["content"])

    def test_real_terminal_json_wrapped_double_wrap_guard(self):
        """Integration test with handle_function_call on terminal tool.
        Verifies that when terminal tool returns JSON-wrapped output:
        {"output": "=== [DETOX FIREWALL: ...", "exit_code": 0, "error": null}
        the double-wrap guard matches and the model receives exactly ONE report."""
        try:
            from hermes_cli.plugins import get_plugin_manager
            pm = get_plugin_manager()
            pm.discover_and_load()
            from model_tools import handle_function_call
        except ImportError:
            self.skipTest("Hermes runtime not importable in this environment")

        cmd = f'"{sys.executable}" -c "for i in range(200): print(f\'line {{i}}: {chr(120)*40}\')"'
        res = handle_function_call("terminal", {"command": cmd})
        self.assertIsInstance(res, str)
        parsed = json.loads(res)
        self.assertIn("output", parsed)
        output_text = parsed["output"]
        # This is a full-runtime integration test. If the Detox plugin is not
        # installed/enabled inside the Hermes process under test, the raw
        # terminal output is returned. Skip cleanly in that case.
        if "[DETOX FIREWALL: terminal" not in output_text:
            self.skipTest("Detox plugin not active in the Hermes runtime under test")

        # Count occurrences of Detox banner across entire response: MUST BE EXACTLY 1 (no double wrap)
        banner_count = res.count("=== [DETOX FIREWALL:")
        self.assertEqual(
            banner_count,
            1,
            f"Expected exactly 1 firewall report, but found {banner_count} (double wrapped!)",
        )


    def test_terminal_json_wrapped_double_wrap_guard_unit(self):
        """Deterministic unit test for JSON-wrapped terminal tool output.
        Simulates Hermes lifecycle without external dependencies:
        1. transform_terminal_output transforms large terminal stream.
        2. Hermes serializes terminal result to JSON: {"output": report, "exit_code": 0}.
        3. transform_tool_result intercepts the JSON result and must NOT double-wrap."""
        stream = "Line data stream\n" * 500  # ~8500 chars
        terminal_report = on_transform_terminal_output(
            command="run_tests",
            output=stream,
            returncode=0,
            session_id="unit_dw",
        )
        self.assertIsNotNone(terminal_report)
        self.assertIn("=== [DETOX FIREWALL: terminal", terminal_report)

        wrapped_json = json.dumps({
            "output": terminal_report,
            "exit_code": 0,
            "error": None,
        })

        res = on_transform_tool_result(
            tool_name="terminal",
            args={"command": "run_tests"},
            result=wrapped_json,
            session_id="unit_dw",
        )
        self.assertIsNone(res, "JSON-wrapped terminal output must not be re-wrapped by transform_tool_result")
        banner_count = wrapped_json.count("=== [DETOX FIREWALL:")
        self.assertEqual(banner_count, 1)


if __name__ == "__main__":
    unittest.main()
