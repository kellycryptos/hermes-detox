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
        self.assertIn("detox_inspect", ctx.tools)
        self.assertIn("detox_search", ctx.tools)
        self.assertIn("detox_status", ctx.tools)
        self.assertIn("detox", ctx.commands)

    def test_small_output_unchanged(self):
        """Outputs below min_size threshold must return None (untouched)."""
        small_text = "Short tool output\nEverything looks good."
        res = on_transform_tool_result(
            tool_name="git_status",
            result=small_text,
            session_id="test_sess",
        )
        self.assertIsNone(res, "Small outputs must return None to leave them unchanged")

    def test_empty_output_handled(self):
        """Empty outputs must return None without raising."""
        self.assertIsNone(on_transform_tool_result(tool_name="test", result=""))
        self.assertIsNone(on_transform_tool_result(tool_name="test", result=None))

    def test_large_output_replaced_and_recoverable(self):
        """Large outputs must be replaced with compact report and recoverable via inspect."""
        # Create 3,000 character output across 60 lines
        lines = [f"Line {i:03d}: System check log entry with payload {i * 42}" for i in range(1, 61)]
        lines[25] = "Line 026: CRITICAL ERROR - Database connection timeout"
        large_output = "\n".join(lines)
        self.assertGreater(len(large_output), 2000)

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

        # Inspect exact lines 24 to 28
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
        noisy_output = "info line\n" * 300 + "Traceback (most recent call last):\n  File 'app.py', line 12\nZeroDivisionError: division by zero\n" + "end line\n" * 50
        
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


if __name__ == "__main__":
    unittest.main()
