# Stage 0 Audit (Amended) — Hermes Detox

> [!IMPORTANT]
> **No code was written or committed.** The local workspace `c:\Users\HP\Downloads\Hernes Detox` is cloned and verified clean on branch `main` tracking `https://github.com/kellycryptos/hermes-detox`.
> All findings below are backed by direct source inspection of the installed **Hermes Agent v0.19.0** (`Python 3.13.13`).

---

## 1. Repository & Account Verification

| Field | Finding | Verified In |
|---|---|---|
| Remote URL | `https://github.com/kellycryptos/hermes-detox` | `git remote -v` |
| HEAD Commit | `ddc1a69` ("Initial commit") | `git log` |
| Branch | `main` | `git branch` |
| Workspace | `c:\Users\HP\Downloads\Hernes Detox` (clean working tree) | `git status` |
| **Repo Owner** | **`kellycryptos`** | GitHub remote inspection |
| **Catalog PR Rule** | The official catalog PR adding `plugin-catalog/hermes-detox.yaml` to `NousResearch/hermes-agent` **must be submitted by `kellycryptos`** (or an authorized major contributor). | Catalog submission rules |

---

## 2. Source Code & API Findings (Hermes Agent v0.19.0)

### 2.1 Interception Seam: `middleware` vs `transform_tool_result`

**Question:** *Is middleware a better interception seam than `transform_tool_result`?*

**Verdict: No, `transform_tool_result` is the correct and superior seam for Detox's firewall, with one key supplement (`transform_terminal_output`).**

**Source Evidence & Reasons:**
1. **Observer Hooks (`post_tool_call`):** In `hermes_cli/plugins.py`, observer hooks are strictly telemetry. Their return values are ignored. They cannot transform or replace outputs.
2. **`tool_execution` Middleware (`hermes_cli/middleware.py:165-195`):**
   - Signature: `callback(next_call, tool_name=..., args=..., **context)`.
   - Middleware is structured as an onion chain wrapping `next_call`. While it could capture the raw return value of `next_call(args)`, it does **not** receive the structured post-execution metadata that Hermes standardizes after tool completion (such as `duration_ms`, `status`, `error_type`, `error_message`, `session_id`, `turn_id`, `tool_call_id`, `api_request_id`).
   - Furthermore, if any middleware in the chain fails to call `next_call` or mishandles exceptions, downstream tools/middleware break.
3. **`transform_tool_result` Hook (`model_tools.py:1320-1348`):**
   - Designed specifically to inspect and modify tool results before insertion into the LLM conversation context.
   - Automatically receives the complete telemetry payload:
     ```python
     hook_results = emit_hook(
         "transform_tool_result",
         tool_name=function_name,
         args=function_args,
         result=result,
         task_id=task_id or "",
         session_id=session_id or "",
         tool_call_id=tool_call_id or "",
         turn_id=turn_id or "",
         api_request_id=api_request_id or "",
         duration_ms=duration_ms,
         status=status,
         error_type=error_type,
         error_message=error_message,
     )
     ```
   - Clean contract: return replacement `str` or `None` to pass through untouched.
   - Built-in fail-open: any unhandled exception in the hook is caught and logged at `DEBUG` (`model_tools.py:1344-1345`), and Hermes returns the original `result` untouched.

---

### 2.2 Terminal Output Bounding & `transform_terminal_output`

**Question:** *Where does Hermes already bound terminal output before `transform_tool_result` runs? What are the limits, and can `transform_terminal_output` capture more?*

**Source Location:** `tools/terminal_tool.py:2800-2830`

**Hermes Bounding Logic:**
1. Line 2803: `invoke_hook("transform_terminal_output", command=command, output=output, returncode=returncode, task_id=effective_task_id or "", env_type=env_type)` fires **first**.
2. Lines 2818-2830: Hermes applies inline truncation:
   ```python
   MAX_OUTPUT_CHARS = get_max_bytes()  # Default: 50,000 characters
   if len(output) > MAX_OUTPUT_CHARS:
       head_chars = int(MAX_OUTPUT_CHARS * 0.4)  # 40% head
       tail_chars = MAX_OUTPUT_CHARS - head_chars  # 60% tail
       omitted = len(output) - head_chars - tail_chars
       truncated_notice = (
           f"\n\n... [OUTPUT TRUNCATED - {omitted} chars omitted out of {len(output)} total] ...\n\n"
       )
       output = output[:head_chars] + truncated_notice + output[-tail_chars:]
   ```
3. Line 2834: `output = strip_ansi(output)` runs.
4. Terminal tool returns `output`.
5. Later, in `model_tools.py:1320`, `transform_tool_result` runs on the returned `result`.

**Crucial Findings:**
- If terminal output exceeds 50,000 characters (or `tool_output.max_bytes`), **the middle chunk is destroyed by Hermes before `transform_tool_result` ever sees it**.
- In contrast, **`transform_terminal_output` receives the 100% full un-truncated `output`** directly from process execution.
- **Architectural Decision for Detox:** Detox should hook `transform_terminal_output` (to save the true un-truncated stdout/stderr to disk for terminal commands) **and** `transform_tool_result` (to firewall all tools and format compact reports).
- **Baseline for Benchmark (Stage 4):** The baseline with Detox off is what the LLM actually receives — i.e., after Hermes's own 50,000-char truncation and ANSI stripping.

---

### 2.3 Hook Precedence ("First String Wins")

**Question:** *What happens when another plugin also returns a string from `transform_tool_result`?*

**Source Evidence (`model_tools.py:1340-1343`):**
```python
for hook_result in hook_results:
    if isinstance(hook_result, str):
        result = hook_result
        break
```
- Hooks execute in registration order.
- The **first non-`None` string** replaces `result` and immediately **breaks the loop**.
- Any subsequent plugin's `transform_tool_result` hook is completely ignored for that tool call.
- Similarly in `terminal_tool.py:2813-2814` for `transform_terminal_output`: `if isinstance(hook_result, str): output = hook_result; break`.

---

### 2.4 Evidence Storage & Concurrency Architecture

- **Path Rule:** Never write inside the plugin installation directory (`~/.hermes/plugins/<name>/`). Plugin update/remove wipes that directory.
- **Persistent Location:** Use `plugins.plugin_storage.plugin_data_dir(name)` or resolve to `<hermes_home>/plugin-data/hermes-detox/`.
- **Database:** Use `plugins.plugin_storage.plugin_db(name)` (SQLite database in **WAL mode**) or initialize `<data_dir>/detox.db` with:
  ```sql
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  ```
  SQLite WAL mode natively supports concurrent readers and serialized atomic writes, handling concurrency safely without corrupting indices or losing records.

---

### 2.5 Tool Signatures & Slash Commands

1. **Tool Handlers:**
   - Signature: `def handler(args: dict, **kwargs) -> str:`
   - Must **never raise** (wrap all operations in try/except and return a JSON error string on failure).
   - Session isolation: Extract `session_id` directly from `kwargs` (e.g., `session_id = kwargs.get("session_id", "default")`).
   - Must always return a JSON string: `json.dumps({...})`.
2. **Slash Command (`/detox`):**
   - Registered via `ctx.register_command("detox", handler, description)`.
   - Handler signature: `def handle_detox_command(args: str) -> str:`.
   - Receives the raw argument string following `/detox` (e.g. `"inspect e_123 1 50"` or `"status"`).
3. **Registration Constraints (`hermes plugins doctor`):**
   - `hermes plugins doctor` blocks network sockets during `register()`.
   - `register()` must perform zero network calls and zero heavy disk I/O.
4. **Declared Capabilities:**
   - `provides_tools` in `plugin.yaml` must list **only and exactly**:
     - `detox_inspect`
     - `detox_search`
     - `detox_status`
   - `provides_hooks`:
     - `transform_tool_result`
     - `transform_terminal_output`

---

### 2.6 Avoiding Standard Library Shadows

To prevent import collision bugs in Python 3.13:
- Use `extract_json.py` (never `extractors/json.py`).
- Use `tool_inspect.py`, `tool_search.py`, `tool_status.py` (never `inspect.py`).
- Use `extract_terminal.py`, `extract_tests.py`, `extract_build.py`, `extract_files.py`, `extract_text.py`.

---

### 2.7 Hermes Environment Details

- **Installed Version:** Hermes Agent v0.19.0 (2026.7.20)
- **Python Version:** 3.13.13 via `uv`
- **Minimum Floor in `plugin.yaml`:** `requires_hermes: ">=0.19.0"`
- **Validation Commands:**
  - `hermes plugins doctor . --ci`
  - `hermes plugins validate . --install-deps` (or catalog script `scripts/validate_plugin_catalog.py`)

---

## 3. Planned File Structure

```
hermes-detox/
├── .gitignore                      # ignore __pycache__, *.pyc, *.db, *.db-wal, *.db-shm, benchmark results
├── plugin.yaml                     # manifest with SemVer floor >=0.19.0 & config_schema
├── __init__.py                     # register(ctx) - light, no IO/sockets
├── store.py                        # SQLite WAL evidence store via plugin_db / plugin_data_dir
├── report.py                       # generic compact report builder
├── tools/
│   ├── __init__.py
│   ├── tool_inspect.py             # detox_inspect handler (args, **kwargs)
│   ├── tool_search.py              # detox_search handler (args, **kwargs)
│   └── tool_status.py              # detox_status handler (args, **kwargs)
├── extractors/                     # Stage 2 additions
│   ├── __init__.py
│   ├── extract_terminal.py
│   ├── extract_tests.py
│   ├── extract_build.py
│   ├── extract_json.py             # non-shadowing
│   ├── extract_files.py
│   └── extract_text.py
├── config.py                       # Stage 3: config loading via ctx.get_config
├── retention.py                    # Stage 3: age & size cap maintenance
└── tests/
    ├── __init__.py
    ├── test_core.py                # Stage 1 tests
    ├── test_extractors.py          # Stage 2 tests
    ├── test_safety.py              # Stage 3 tests
    └── fixtures/                   # real fixtures for terminal, test, json, build outputs
```

---

## 4. Stage 1 Milestone Plan

1. Create `.gitignore` to block `.pyc`, `__pycache__`, evidence databases (`*.db`, `*.db-*`), and scratch files.
2. Create `plugin.yaml` declaring `requires_hermes: ">=0.19.0"`, `provides_hooks`, `provides_tools`, and `config_schema`.
3. Create `store.py` implementing SQLite WAL storage under `plugin_data_dir("hermes-detox")` with safe file permissions (`0o600`), storing: evidence ID, session ID, tool name, timestamp, original output, original size, transformed size, content type, and status.
4. Create `report.py` implementing generic compact report formatting with verbatim error preservation.
5. Create `__init__.py` registering hooks (`transform_tool_result` and `transform_terminal_output`), tools (`detox_inspect`, `detox_search`, `detox_status`), and `/detox` command.
6. Create `tests/test_core.py` covering:
   - Output > threshold replaced and fully recoverable via `detox_inspect`.
   - Small output (< threshold) passes through completely unchanged.
   - Storage exception fails open (returns original output).
   - Empty output handled cleanly.
   - Exact line slice recovery (`start_line`, `end_line`) verified against original.
   - Error status outputs retain error lines verbatim.
7. Run test suite, doctor check, and validation command.

---

*Stage 0 Audit complete with all amendments resolved. Awaiting your approval to proceed to Stage 1.*
