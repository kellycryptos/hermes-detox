"""Stage 3 Safety, Concurrency, Retention, and Security Tests for Hermes Detox."""

from __future__ import annotations

import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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

from hermes_detox.config import DEFAULT_EXCLUDED_TOOLS, DetoxConfig, get_config, set_config
from hermes_detox.detox_tools.tool_inspect import handle_detox_inspect
from hermes_detox.detox_tools.tool_search import handle_detox_search
from hermes_detox.detox_tools.tool_status import handle_detox_status
from hermes_detox.retention import maybe_run_retention_prune, run_retention_prune
from hermes_detox.store import EvidenceStore, get_db_path, set_storage_dir_override

detox_mod = _mod
on_transform_tool_result = _mod.on_transform_tool_result
on_transform_terminal_output = _mod.on_transform_terminal_output
on_session_reset = _mod.on_session_reset
handle_detox_slash_command = _mod.handle_detox_slash_command


class TestDetoxSafetyAndRetention(unittest.TestCase):
    """Test suite covering concurrency, retention pruning, and security guardrails."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="detox_safety_test_"))
        set_storage_dir_override(self.test_dir)
        EvidenceStore.reset_instance()
        set_config(DetoxConfig())

    def tearDown(self):
        EvidenceStore.reset_instance()
        set_storage_dir_override(None)
        set_config(DetoxConfig())
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_concurrent_writes_wal_mode(self):
        """10 concurrent threads inserting into SQLite WAL mode simultaneously.
        Verifies zero deadlocks, zero 'database is locked' errors, and 100% record integrity."""
        store = EvidenceStore.get_instance()
        num_threads = 10
        records_per_thread = 5

        def _worker(thread_idx: int) -> list[str]:
            thread_ids = []
            for item_idx in range(records_per_thread):
                body = f"Thread {thread_idx} log entry {item_idx}\n" + ("Payload data line\n" * 200)
                ev_id = store.save(
                    session_id=f"sess_thread_{thread_idx}",
                    tool_name="worker_tool",
                    original_output=body,
                    transformed_size=200,
                    content_type="text/plain",
                )
                thread_ids.append(ev_id)
            return thread_ids

        all_ids = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(_worker, i) for i in range(num_threads)]
            for fut in concurrent.futures.as_completed(futures):
                all_ids.extend(fut.result())

        self.assertEqual(len(all_ids), num_threads * records_per_thread)
        self.assertEqual(store.count_records(), num_threads * records_per_thread)

        # Confirm all records are cleanly readable
        for ev_id in all_ids:
            rec = store.get(ev_id)
            self.assertIsNotNone(rec, f"Record {ev_id} must exist in store")
            self.assertIn("Payload data line", rec["original_output"])

    def test_age_based_retention_prune(self):
        """Records older than retention_days are purged, while newer records are preserved."""
        store = EvidenceStore.get_instance()
        conn = store._get_conn()

        now = datetime.datetime.now(datetime.timezone.utc)
        ts_45d = (now - datetime.timedelta(days=45)).isoformat()
        ts_35d = (now - datetime.timedelta(days=35)).isoformat()
        ts_10d = (now - datetime.timedelta(days=10)).isoformat()
        ts_now = now.isoformat()

        with conn:
            conn.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ev_old_45", "s1", "t", ts_45d, "old 45 data", 11, 0, "text/plain", "success"),
            )
            conn.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ev_old_35", "s1", "t", ts_35d, "old 35 data", 11, 0, "text/plain", "success"),
            )
            conn.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ev_keep_10", "s1", "t", ts_10d, "keep 10 data", 12, 0, "text/plain", "success"),
            )
            conn.execute(
                "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("ev_keep_now", "s1", "t", ts_now, "keep now data", 13, 0, "text/plain", "success"),
            )

        self.assertEqual(store.count_records(), 4)

        # Run age prune with 30 days retention
        purged = store.purge_older_than(30)
        self.assertEqual(purged, 2)
        self.assertEqual(store.count_records(), 2)

        self.assertIsNone(store.get("ev_old_45"))
        self.assertIsNone(store.get("ev_old_35"))
        self.assertIsNotNone(store.get("ev_keep_10"))
        self.assertIsNotNone(store.get("ev_keep_now"))

    def test_size_cap_retention_prune(self):
        """When database exceeds size cap, oldest records are pruned until within limit."""
        store = EvidenceStore.get_instance()
        now = datetime.datetime.now(datetime.timezone.utc)

        # Insert 10 records with sequential timestamps
        for i in range(10):
            ts = (now - datetime.timedelta(minutes=10 - i)).isoformat()
            payload = f"Payload {i}\n" + ("x" * 20000)
            conn = store._get_conn()
            with conn:
                conn.execute(
                    "INSERT INTO evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"ev_seq_{i}", "s1", "t", ts, payload, len(payload), 0, "text/plain", "success"),
                )

        initial_count = store.count_records()
        self.assertEqual(initial_count, 10)
        initial_size = store.get_db_size()
        self.assertGreater(initial_size, 50000)

        # Enforce size cap smaller than initial size
        purged = store.enforce_size_cap(initial_size // 2)
        self.assertGreater(purged, 0)
        remaining = store.count_records()
        self.assertLess(remaining, 10)
        # Oldest records should have been deleted first
        self.assertIsNone(store.get("ev_seq_0"))

    def test_retention_throttling(self):
        """Retention prune is throttled: running it twice in quick succession skips the second."""
        cfg = DetoxConfig(retention_days=30, max_store_size_mb=100)
        set_config(cfg)
        store = EvidenceStore.get_instance()

        res1 = maybe_run_retention_prune(store=store, config=cfg, min_interval_secs=3600)
        self.assertIsNotNone(res1)
        self.assertTrue(res1["success"])

        # Second call immediately after should be throttled (returns None)
        res2 = maybe_run_retention_prune(store=store, config=cfg, min_interval_secs=3600)
        self.assertIsNone(res2, "Subsequent prune within throttle window must return None")

    def test_post_compaction_session_rotation(self):
        """Verify cross-session evidence inspection and search scoping after compaction rotates session ID.
        1. detox_inspect with explicit evidence_id works across session rotation (authorizing access by ID).
        2. detox_search without an evidence_id remains strictly session-scoped to prevent cross-session leakage.
        3. detox_search with an explicit evidence_id searches the targeted pre-compaction record.
        4. relinking session brings pre-compaction records into the new session's unscoped search pool."""
        store = EvidenceStore.get_instance()
        lines = [f"Pre-compaction log line {i}" for i in range(250)]
        lines[50] = "CRITICAL_PRE_COMPACTION_MARKER"
        raw_output = "\n".join(lines)

        report = on_transform_tool_result(
            tool_name="pre_compact_build",
            result=raw_output,
            session_id="sess_pre_compact",
        )
        self.assertIsNotNone(report)
        import re
        ev_id = re.search(r"evidence: `(ev_[a-f0-9]+)`", report).group(1)

        # 1. Scoped inspect in pre-compaction session succeeds
        res_pre = json.loads(handle_detox_inspect({"evidence_id": ev_id, "start_line": 51, "end_line": 51}, session_id="sess_pre_compact"))
        self.assertTrue(res_pre["success"])
        self.assertIn("CRITICAL_PRE_COMPACTION_MARKER", res_pre["content"])

        # 2. Compaction occurs and rotates session to sess_post_compact
        # Model retains evidence_id in summary context: detox_inspect with explicit evidence_id SUCCEEDS
        res_post = json.loads(handle_detox_inspect({"evidence_id": ev_id, "start_line": 51, "end_line": 51}, session_id="sess_post_compact"))
        self.assertTrue(res_post["success"], "Model must be able to inspect pre-compaction evidence by explicit ID after session rotation")
        self.assertIn("CRITICAL_PRE_COMPACTION_MARKER", res_post["content"])

        # 3. detox_search WITHOUT evidence_id remains strictly session-scoped (returns 0 matches)
        res_search_unscoped = json.loads(handle_detox_search({"query": "CRITICAL_PRE_COMPACTION_MARKER"}, session_id="sess_post_compact"))
        self.assertTrue(res_search_unscoped["success"])
        self.assertEqual(len(res_search_unscoped["results"]), 0, "Unscoped search in new session must not leak pre-compaction evidence")

        # 4. detox_search WITH explicit evidence_id succeeds across rotation
        res_search_scoped = json.loads(handle_detox_search({"query": "CRITICAL_PRE_COMPACTION_MARKER", "evidence_id": ev_id}, session_id="sess_post_compact"))
        self.assertTrue(res_search_scoped["success"])
        self.assertEqual(len(res_search_scoped["results"]), 1, "Search with explicit evidence_id must search targeted pre-compaction record")

        # 5. After store.relink_session is called, pre-compaction evidence joins the new session search pool
        store.relink_session("sess_pre_compact", "sess_post_compact")
        res_search_relinked = json.loads(handle_detox_search({"query": "CRITICAL_PRE_COMPACTION_MARKER"}, session_id="sess_post_compact"))
        self.assertTrue(res_search_relinked["success"])
        self.assertEqual(len(res_search_relinked["results"]), 1, "Relinked session brings evidence into new session search pool")

    def test_media_and_base64_payloads_left_untouched(self):
        """Tool outputs containing base64 images or media URIs must bypass Detox to protect vision."""
        # 1. Data URI PNG image payload (>8,000 chars)
        fake_png_b64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ" + ("A" * 8000)
        res_img = on_transform_tool_result(
            tool_name="render_graph",
            result=fake_png_b64,
            session_id="media_sess",
        )
        self.assertIsNone(res_img, "Base64 data:image URI must return None (untouched)")

        # 2. Video data URI
        fake_vid_b64 = "data:video/mp4;base64,AAAAHGZ0eXBtcDQyAAAAAG1wNDJpc29t" + ("B" * 8000)
        res_vid = on_transform_tool_result(
            tool_name="record_screen",
            result=fake_vid_b64,
            session_id="media_sess",
        )
        self.assertIsNone(res_vid, "Base64 data:video URI must return None (untouched)")

        # 3. Raw base64 terminal output
        raw_b64_term = ";base64," + ("C" * 8000)
        res_term = on_transform_terminal_output(
            command="cat image.b64",
            output=raw_b64_term,
            returncode=0,
            env_type="bash",
            session_id="media_sess",
        )
        self.assertIsNone(res_term, "Raw base64 terminal stream must return None (untouched)")

    def test_default_excluded_tools(self):
        """Sensible default excluded_tools (vision, media, file edits) must be active out of the box."""
        cfg = get_config()
        self.assertIn("browser_vision", cfg.excluded_tools)
        self.assertIn("browser_snapshot", cfg.excluded_tools)
        self.assertIn("image_generate", cfg.excluded_tools)
        self.assertIn("patch", cfg.excluded_tools)
        self.assertIn("write_file", cfg.excluded_tools)

        large_payload = "Some line\n" * 800
        # browser_snapshot output must not be intercepted
        res_snap = on_transform_tool_result(tool_name="browser_snapshot", result=large_payload, session_id="s1")
        self.assertIsNone(res_snap)
        # patch output must not be intercepted
        res_patch = on_transform_tool_result(tool_name="patch", result=large_payload, session_id="s1")
        self.assertIsNone(res_patch)

    def test_redaction_behavior_with_secrets(self):
        """Verify that Detox redacts secrets before storing or reporting.
        Fake secrets in several shapes (sk- style key, ghp_ token, Bearer header,
        KEY=value env line, JWT) must be absent from:
        1. Stored database bytes / records
        2. Delivered compact report
        3. detox_inspect retrieved output
        4. detox_search results
        """
        import re

        # Ensure agent.redact is importable
        try:
            import agent.redact
        except ImportError:
            for candidate in (
                os.environ.get("HERMES_AGENT_PATH"),
                r"C:\Users\HP\AppData\Local\hermes\hermes-agent",
                "/tmp/hermes-agent",
            ):
                if candidate and os.path.isdir(candidate) and candidate not in sys.path:
                    sys.path.insert(0, candidate)
                    try:
                        import agent.redact
                        break
                    except ImportError:
                        pass

        # Build dynamic fake secrets to prevent static scanner alerts
        sk_key = "sk-ant-" + "api03-" + "abcdef1234567890abcdef1234567890"
        ghp_token = "ghp_" + "0123456789abcdefghijklmnopqrstuvwxyz"
        bearer_header = f"Authorization: Bearer {sk_key}"
        env_secret_val = "SuperSecretPassw0rd123!"
        env_line = f"DATABASE_PASSWORD={env_secret_val}"
        jwt_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        fake_secrets = [sk_key, ghp_token, bearer_header, env_secret_val, jwt_token]

        lines = [
            "Configuration initialized.",
            f"AUTH_TOKEN={sk_key}",
            f"GITHUB_TOKEN={ghp_token}",
            bearer_header,
            env_line,
            f"JWT_SESSION={jwt_token}",
            "Connection established successfully.",
        ] + [f"Log stream record {i:04d}: Telemetry event packet payload data" for i in range(300)]
        raw_output = "\n".join(lines)

        report = on_transform_tool_result(
            tool_name="init_service",
            result=raw_output,
            session_id="sec_sess",
        )
        self.assertIsNotNone(report)

        # 1. Assert secrets absent from compact report
        for sec in fake_secrets:
            self.assertNotIn(sec, report, f"Secret {sec[:12]}... must not appear in compact report")

        # 2. Assert secrets absent from database records & database bytes
        store = EvidenceStore.get_instance()
        conn = store._get_conn()
        row = conn.execute("SELECT original_output FROM evidence WHERE session_id = 'sec_sess'").fetchone()
        stored_output = row[0]
        for sec in fake_secrets:
            self.assertNotIn(sec, stored_output, f"Secret {sec[:12]}... must not be stored in SQLite record")

        db_path = get_db_path()
        if db_path.exists():
            db_bytes = db_path.read_bytes()
            for sec in fake_secrets:
                self.assertNotIn(sec.encode("utf-8"), db_bytes, f"Secret {sec[:12]}... must not appear in SQLite file bytes")

        # 3. Assert secrets absent from detox_inspect output
        ev_id = re.search(r"evidence: `(ev_[a-f0-9]+)`", report).group(1)
        inspect_raw = handle_detox_inspect({"evidence_id": ev_id, "start_line": 1, "end_line": 10}, session_id="sec_sess")
        inspect_data = json.loads(inspect_raw)
        self.assertTrue(inspect_data.get("success"))
        for sec in fake_secrets:
            self.assertNotIn(sec, inspect_raw, f"Secret {sec[:12]}... must not appear in detox_inspect output")
            for line in inspect_data.get("lines", []):
                self.assertNotIn(sec, line)

        # 4. Assert secrets absent from detox_search output
        search_terms = ["abcdef1234567890", "ghijklmnopqrst", "SuperSecretPassw0rd", "SflKxwRJSMe"]
        for term in search_terms:
            search_raw = handle_detox_search({"query": term, "evidence_id": ev_id}, session_id="sec_sess")
            search_data = json.loads(search_raw)
            self.assertEqual(search_data.get("matches_count", 0), 0, f"detox_search must find 0 matches for secret query '{term}'")

    def test_redaction_import_failure_stores_nothing(self):
        """If agent.redact cannot be imported, fail open: return None and store nothing."""
        from unittest.mock import patch
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "agent.redact" in name or name == "agent":
                raise ImportError("Simulated missing agent.redact module")
            return real_import(name, *args, **kwargs)

        store = EvidenceStore.get_instance()
        initial_count = store.count_records()

        large_payload = "Some output line\n" * 400  # > 6000 chars

        with patch("builtins.__import__", side_effect=mock_import):
            res_tool = on_transform_tool_result(
                tool_name="some_tool",
                result=large_payload,
                session_id="import_fail_sess",
            )
            self.assertIsNone(res_tool, "Tool hook must fail open (return None) when redact import fails")

            res_term = on_transform_terminal_output(
                command="cat large.txt",
                output=large_payload,
                returncode=0,
                session_id="import_fail_sess",
            )
            self.assertIsNone(res_term, "Terminal hook must fail open (return None) when redact import fails")

        self.assertEqual(
            store.count_records(),
            initial_count,
            "No evidence records may be saved when redaction helpers are unavailable",
        )

    def test_storage_unavailable_without_plugin_data_dir(self):
        """If plugins.plugin_storage.plugin_data_dir cannot be imported, store nothing and return None."""
        from unittest.mock import patch
        from hermes_detox.store import resolve_data_dir, set_storage_dir_override
        # Clear test storage override so resolve_data_dir attempts real resolution
        set_storage_dir_override(None)
        EvidenceStore.reset_instance()

        try:
            with patch.dict("sys.modules", {"plugins.plugin_storage": None, "plugins": None}):
                self.assertIsNone(resolve_data_dir())
                store = EvidenceStore.get_instance()
                self.assertFalse(store.is_available())

                large_payload = "Line of output\n" * 500  # > 6,000 chars
                res_tool = on_transform_tool_result(
                    tool_name="some_tool",
                    result=large_payload,
                    session_id="no_storage_sess",
                )
                self.assertIsNone(res_tool, "Tool hook must return None when storage is unavailable")

                res_term = on_transform_terminal_output(
                    command="echo test",
                    output=large_payload,
                    returncode=0,
                    session_id="no_storage_sess",
                )
                self.assertIsNone(res_term, "Terminal hook must return None when storage is unavailable")

                self.assertEqual(store.count_records(), 0, "No records should be stored when storage is unavailable")
        finally:
            # Restore test directory override
            set_storage_dir_override(self.test_dir)
            EvidenceStore.reset_instance()

    def test_user_excluded_tools_extends_defaults(self):
        """User-configured excluded_tools must extend the 9 default tools instead of replacing them."""
        # 1. Configured via from_dict (Hermes config loader)
        cfg_dict = DetoxConfig.from_dict({"excluded_tools": ["custom_telemetry_tool", "my_special_tool"]})
        self.assertIn("custom_telemetry_tool", cfg_dict.excluded_tools)
        self.assertIn("my_special_tool", cfg_dict.excluded_tools)
        for default_tool in DEFAULT_EXCLUDED_TOOLS:
            self.assertIn(default_tool, cfg_dict.excluded_tools, f"Default tool '{default_tool}' must be preserved")

        # 2. Configured via direct dataclass constructor
        cfg_direct = DetoxConfig(excluded_tools=["another_user_tool"])
        self.assertIn("another_user_tool", cfg_direct.excluded_tools)
        for default_tool in DEFAULT_EXCLUDED_TOOLS:
            self.assertIn(default_tool, cfg_direct.excluded_tools, f"Default tool '{default_tool}' must be preserved")

    def test_excluded_tools_configuration(self):
        """Tools in excluded_tools configuration must never be intercepted, even if large."""
        cfg = DetoxConfig(min_size=6000, excluded_tools=["secret_dump_tool", "my_custom_tool"])
        set_config(cfg)

        large_payload = "Data row\n" * 800  # ~7,200 chars

        # Excluded tool -> returns None
        res_excluded = on_transform_tool_result(
            tool_name="secret_dump_tool",
            result=large_payload,
            session_id="excl_sess",
        )
        self.assertIsNone(res_excluded, "Excluded tool must return None")

        # Non-excluded tool -> intercepted
        res_normal = on_transform_tool_result(
            tool_name="normal_tool",
            result=large_payload,
            session_id="excl_sess",
        )
        self.assertIsNotNone(res_normal, "Non-excluded tool must be transformed")

    def test_fail_open_on_corrupt_database(self):
        """If SQLite database file is corrupted or unwriteable, fail open without crashing."""
        db_path = EvidenceStore.get_instance().db_path
        EvidenceStore.reset_instance()

        # Overwrite DB with corrupted binary data
        with open(db_path, "wb") as f:
            f.write(b"CORRUPTED_GARBAGE_BYTES_NOT_A_SQLITE_DATABASE" * 100)

        large_output = "System log line\n" * 600
        res = on_transform_tool_result(
            tool_name="critical_task",
            result=large_output,
            session_id="corrupt_sess",
        )
        self.assertIsNone(res, "Detox must fail open (return None) when database is corrupted")

    def test_slash_command_purge_and_status(self):
        """Test /detox purge and /detox status slash commands."""
        store = EvidenceStore.get_instance()
        large_output = "Diagnostic report\n" + ("log entry\n" * 400)
        on_transform_tool_result(tool_name="test_tool", result=large_output, session_id="cmd_sess")

        status_msg = handle_detox_slash_command("status")
        self.assertIn("Outputs intercepted:", status_msg)
        self.assertIn("Database size:", status_msg)
        self.assertIn("Stored records:", status_msg)

        purge_msg = handle_detox_slash_command("purge")
        self.assertIn("Detox Retention Purge Completed:", purge_msg)
        self.assertIn("Records remaining:", purge_msg)


if __name__ == "__main__":
    unittest.main()
