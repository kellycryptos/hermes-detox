# Stage 1: Minimal Viable Core — Verification Report

> [!IMPORTANT]
> **Stage 1 is complete.** All 10 core unit tests pass in 0.16s, the plugin is registered and enabled in Hermes Agent >=0.22.3, and a live execution run verified the firewall interception and exact line recovery.

---

## 1. What Changed (Files Committed)

| File | Purpose |
|---|---|
| `.gitignore` | Ignores `__pycache__`, `*.pyc`, `*.db`, `*.db-*`, `benchmark/results/` |
| `plugin.yaml` | Declares `requires_hermes: ">=0.22.3"`, `provides_hooks`, `provides_tools`, and `config_schema` |
| `__init__.py` | Zero-I/O `register(ctx)`, `transform_tool_result`, `transform_terminal_output`, `/detox` slash command |
| `store.py` | Thread-safe SQLite store in WAL mode, restrictive permissions (`0o600`), 1-based exact line slicing |
| `report.py` | Compact report generator, head/tail preservation, diagnostic lines, and verbatim error blocks |
| `detox_tools/tool_inspect.py` | `detox_inspect` handler `(args: dict, **kwargs) -> str` |
| `detox_tools/tool_search.py` | `detox_search` handler `(args: dict, **kwargs) -> str` |
| `detox_tools/tool_status.py` | `detox_status` handler `(args: dict, **kwargs) -> str` |
| `tests/test_core.py` | 10 comprehensive unit tests covering all Stage 1 gates |

Commit hash: `0ca3599` ("feat: Stage 1 minimal viable core (hooks, SQLite WAL store, compact report, inspect/search/status tools)").

---

## 2. Test Suite Execution Output

Command: `uv run python tests\test_core.py -v`

```text
test_detox_search_tool (__main__.TestDetoxCore.test_detox_search_tool)
Search tool returns matching lines with accurate line numbers. ... ok
test_detox_status_metrics (__main__.TestDetoxCore.test_detox_status_metrics)
Status tool calculates characters saved accurately. ... ok
test_empty_output_handled (__main__.TestDetoxCore.test_empty_output_handled)
Empty outputs must return None without raising. ... ok
test_error_status_preserved_verbatim (__main__.TestDetoxCore.test_error_status_preserved_verbatim)
Results with error status/type/message must preserve error details verbatim. ... ok
test_exact_line_retrieval (__main__.TestDetoxCore.test_exact_line_retrieval)
Verify boundary precision for line retrieval (1-based inclusive). ... ok
test_large_output_replaced_and_recoverable (__main__.TestDetoxCore.test_large_output_replaced_and_recoverable)
Large outputs must be replaced with compact report and recoverable via inspect. ... ok
test_registration_integrity (__main__.TestDetoxCore.test_registration_integrity)
Verify register(ctx) registers exactly the declared hooks, tools, and commands. ... ok
test_slash_command_dispatch (__main__.TestDetoxCore.test_slash_command_dispatch)
Verify /detox subcommands return clean human-readable strings. ... ok
test_small_output_unchanged (__main__.TestDetoxCore.test_small_output_unchanged)
Outputs below min_size threshold must return None (untouched). ... ok
test_storage_failure_fails_open (__main__.TestDetoxCore.test_storage_failure_fails_open)
If storage write raises an error, transform_tool_result must fail open (return None). ... ok

----------------------------------------------------------------------
Ran 10 tests in 0.159s

OK
```

---

## 3. Hermes Agent Live Discovery & Enabled Status

Hermes CLI commands executed in real environment:

```text
> hermes plugins enable hermes-detox
✓ Plugin hermes-detox enabled. Takes effect on next session.

> hermes plugins list --enabled
┌──────────────┬─────────┬─────────┬─────────────────────────────────┬────────┐
│ Name         │ Status  │ Version │ Description                     │ Source │
├──────────────┼─────────┼─────────┼─────────────────────────────────┼────────┤
│ hermes-detox │ enabled │ 0.1.0   │ Tool output firewall for Hermes │ git    │
│              │         │         │ Agent. Compresses noisy tool    │        │
│              │         │         │ results, saves full originals   │        │
│              │         │         │ locally, and enables exact line │        │
│              │         │         │ retrieval.                      │        │
└──────────────┴─────────┴─────────┴─────────────────────────────────┴────────┘
```

---

## 4. Live Hermes Hook Execution & Exact Line Retrieval

Executed through Hermes Agent's live `handle_function_call`:

### Step 1: Tool Execution Intercepted
- Tool: `mock_noisy_query`
- Original Output: **6,499 characters**, 86 lines
- Transformed Output Received by Agent: **1,354 characters** (79.2% context reduction)
- Evidence ID: `ev_cbd63fe3f9aa`

**Preview of what the agent received:**
```text
=== [DETOX FIREWALL: mock_noisy_query] ===
Original output (6,499 chars, 86 lines) saved to evidence: `ev_cbd63fe3f9aa`

--- Head (Lines 1-5) ---
   1 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   2 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   3 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   4 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   5 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

--- Diagnostic Findings (1 lines) ---
  81 [ERROR] | ERROR: connection refused on port 5432

--- Tail (Lines 82-86) ---
  82 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  83 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  84 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  85 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  86 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

--- Retrieval ---
To inspect exact lines, call `detox_inspect(evidence_id="ev_cbd63fe3f9aa", start_line=<N>, end_line=<M>)`.
To search lines, call `detox_search(evidence_id="ev_cbd63fe3f9aa", query="<phrase>")`.
=== [END DETOX REPORT `ev_cbd63fe3f9aa`] ===
```

### Step 2: Agent Queries `detox_inspect` for Exact Lines 79–83
Call: `detox_inspect(evidence_id="ev_cbd63fe3f9aa", start_line=79, end_line=83)`

**Retrieved Result:**
```text
  79 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  80 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  81 | ERROR: connection refused on port 5432
  82 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
  83 | line: debug info payload xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 5. Architectural Rule Compliance Check

1. **Fail Open:** Verified in `test_storage_failure_fails_open`. When database writes encounter any exception, `on_transform_tool_result` logs the error and returns `None`, leaving the original result completely untouched.
2. **Zero Dependencies:** All code uses Python standard library (`sqlite3`, `pathlib`, `json`, `os`, `re`, `shlex`, `threading`).
3. **No Namespace Shadowing:** Created `detox_tools/` instead of `tools/` to avoid shadowing Hermes's internal `tools.registry`.
4. **No Secrets / Artifacts in Repo:** Verified `git ls-files` tracks only 12 clean source files; evidence databases and caches are ignored.
