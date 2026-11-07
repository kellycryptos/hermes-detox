# Hermes Detox

Your context window deserves protection.

[![License: MIT](https://img.shields.io/badge/license-MIT-purple.svg)](LICENSE)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20external-success.svg)](#security-and-privacy)
[![Hermes](https://img.shields.io/badge/hermes--agent-%3E%3D0.19.0-blueviolet.svg)](#compatibility)
[![Tests](https://img.shields.io/badge/tests-74-blue.svg)](#development)
[![Context Reduction](https://img.shields.io/badge/context%20reduction-about%2088%25-blue.svg)](#benchmark)

Hermes Detox is a plugin for [Hermes Agent](https://hermes-agent.nousresearch.com/) that stops huge tool outputs from flooding the model's context. When a tool returns a large result, Detox saves the full original on your machine, hands the model a short report with an evidence ID, and lets the model pull back exact lines or search the original whenever it needs them.

The model reads less. Nothing is thrown away.

Built for the Hermes Agent Plugin Hackathon.

> 📺 **Watch the Walkthrough Demo Video on X:** [x.com/Kellycryptos/status/2119068376085458987](https://x.com/Kellycryptos/status/2119068376085458987)

---

## Why this matters

Agents spend most of their working life reading tool output: test runs, build logs, directory listings, API responses. A single failing test suite can put thousands of tokens of passing lines in front of the model, and every one of them costs money, pushes useful history out of the window, and gives the model more noise to dig through.

Hermes already limits terminal output, and that limit has a cost of its own. In Hermes 0.19.0, terminal output over 50,000 characters is cut down to the first 40% and the last 60%, and the middle is dropped. The root cause of a failure often sits in that middle. The model never sees it, and no tool can bring it back.

Detox changes the trade. It captures the full output before that cut happens, keeps it locally, and gives the model a compact view built from the lines that matter: errors, failures, tracebacks, counts, and file locations. If the compact view is not enough, the model asks for more and gets the exact original text.

---

## How it works

```
Tool runs (terminal, tests, compiler, file search, API call)
  |
  v
Detox hook (transform_terminal_output / transform_tool_result)
  |
  |-- Skipped: under the size threshold, an excluded tool,
  |   Detox's own tools, media or base64 data, background
  |   process notifications
  |
  |-- Large output:
  |   1. Save the full original to local SQLite
  |   2. Pick an extractor for the output type
  |   3. Build a compact report with an evidence ID
  |   4. Use the report only if it is small enough
  |
  v
Model receives the compact report
  |
  v
Model calls detox_inspect or detox_search for exact lines
```

A report is only used when it comes out at most 55% of the original size. If an output can't be compacted well, the model gets the original untouched.

Any error inside Detox, such as a full disk, a locked database, or a failing extractor, makes the hook return nothing. Hermes then handles the output exactly as it would without the plugin.

---

## What the model sees

A compact report contains the tool name, the original size, an evidence ID, the first and last few lines, every error and warning line with its original line number, a summary built by a content-aware extractor, and a note on how to retrieve the rest. Line numbers in the report match the stored original, so a number the model reads can be passed straight to `detox_inspect`.

---

## Install

```bash
hermes plugins install kellycryptos/hermes-detox
hermes plugins enable hermes-detox
```

Or clone it by hand:

```bash
git clone https://github.com/kellycryptos/hermes-detox.git ~/.hermes/plugins/hermes-detox
hermes plugins enable hermes-detox
```

Start a new Hermes session and run `/detox status` to confirm it loaded.

---

## Usage

Detox works on its own. Run noisy commands as usual and the model receives compact reports.

### Slash commands

| Command | What it does |
|---|---|
| `/detox status` | Shows outputs intercepted, characters in and out, characters saved, record count, and database size |
| `/detox inspect <evidence_id> [start] [end]` | Prints exact lines from stored evidence |
| `/detox search <phrase> [evidence_id]` | Searches stored outputs for a phrase |
| `/detox purge [days]` | Runs retention cleanup, or removes evidence older than the given number of days |

### Tools the model can call

- **`detox_inspect`** returns exact lines from a stored output:
  ```json
  { "evidence_id": "ev_4f1b8a92e10c", "start_line": 40, "end_line": 55 }
  ```

- **`detox_search`** finds matching lines with their original line numbers:
  ```json
  { "query": "NullPointerException", "evidence_id": "ev_4f1b8a92e10c", "max_results": 10 }
  ```

- **`detox_status`** reports firewall statistics for the session.

Detox never compacts the results of its own three tools, so a long `detox_inspect` result always reaches the model in full.

---

## Supported output types

Each extractor falls back to a generic report when it can't process an output with confidence.

| Type | What is preserved |
|---|---|
| Test runs (pytest, unittest, jest, cargo test, go test) | Passed, failed, and skipped counts, failing test names, assertion messages, relevant traces |
| Build logs (gcc, clang, rustc, TypeScript) | Diagnostics with file and line, dependency and linker errors |
| Terminal output | Exit code, tracebacks, error lines, final status |
| JSON | Structure, key fields, identifiers, counts, and error fields, with numbers kept exact |
| File listings (find, ls -laR, tree) | Totals, distribution by directory, notable files |
| Plain text | Headings and alert blocks |

---

## Configuration

Settings are declared in `plugin.yaml` and read through Hermes's plugin configuration.

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Master switch |
| `min_size` | `6000` | Outputs below this many characters are left alone |
| `max_report_chars` | `3000` | Character budget for a compact report |
| `max_ratio` | `0.55` | A report must be at most this fraction of the original, or the original is kept |
| `head_lines` | `5` | Leading lines shown in a report |
| `tail_lines` | `5` | Trailing lines shown in a report |
| `excluded_tools` | see below | Tools Detox never touches |
| `retention_days` | `30` | Evidence older than this is pruned |
| `max_store_size_mb` | `100` | Oldest evidence is removed when the database passes this size |
| `debug` | `false` | Verbose logging |

**Default exclusions:** `browser_vision`, `browser_snapshot`, `image_generate`, `video_generate`, `video_analyze`, `vision_analyze`, `text_to_speech`, `patch`, and `write_file`. Tools you add to `excluded_tools` are added to this list and don't replace it.

Retention cleanup runs at most once every six hours, at session reset or through `/detox purge`. It never runs while a tool result is being processed.

---

## Reliability

- **Fail open on every path.** Storage errors, extractor errors, and database corruption all return the original output.
- **No double wrapping.** A result that already carries a Detox report is never compacted again.
- **Background process notifications** from Hermes are ignored.
- **Images, audio, video, and base64 data** are left untouched.
- **Evidence IDs are paired with the output** inside the same hook call, so parallel terminal commands can't swap IDs.
- **The SQLite database runs in WAL mode** with a busy timeout and was tested with ten concurrent writers.
- **Reports are checked against the stored original.** A test confirms no line in a report is missing from the original or carries a wrong line number, and that every error line is either in the report or retrievable by line number.

---

## Security and privacy

- **Everything stays local.** Detox makes no network requests, sends no telemetry, and has no dependencies beyond the Python standard library.
- **Evidence is stored in `<hermes home>/plugin-data/hermes-detox/detox.db`.** On Windows this is `%LOCALAPPDATA%\hermes\plugin-data\hermes-detox\detox.db`. On Linux and macOS it is `~/.hermes/plugin-data/hermes-detox/detox.db`.
- **The database is not encrypted.** On Linux and macOS the directory and file are created with mode `0700` and `0600`. On Windows access follows your user profile permissions, which means your account and administrators can read it.
- **Detox stores raw output,** so anything a tool prints can end up in the database, including credentials that show up in logs or environment dumps. Hermes redacts secrets in outbound messages when `security.redact_secrets` is on, so a stored secret may be masked before the model sees it. With that setting off, it is not.
- **Anyone using the same Hermes profile who knows an evidence ID can read that evidence,** even from another session. IDs are random, but treat them as sensitive.
- Use `/detox purge` to remove evidence at any time, or lower `retention_days`.

---

## Benchmark

Run it yourself with `python benchmarks/run_benchmark.py`.

These figures come from synthetic fixtures built to resemble common developer output. They are character counts, and token numbers are estimates at four characters per token. For terminal output over the cap, the baseline is the 50,000 characters Hermes delivers to the model, not the full captured size.

| Scenario | Baseline chars | Delivered chars | Reduction | Est. tokens saved |
|---|---|---|---|---|
| Pytest run (3 failures, 42 passes) | 15,317 | 2,869 | 81.3% | 3,112 |
| C++ build log (4 files) | 9,902 | 1,894 | 80.9% | 2,002 |
| JSON API payload (50 records) | 29,923 | 1,973 | 93.4% | 6,987 |
| Directory listing (580 files) | 15,155 | 910 | 94.0% | 3,561 |
| Server trace log (420 lines) | 35,448 | 1,822 | 94.9% | 8,407 |
| Massive terminal log (106,913 captured, baseline capped at 50,000) | 50,000 | 1,487 | 97.0% | 12,129 |
| Output with secret-like strings | 11,752 | 1,032 | 91.2% | 2,680 |
| Short output below threshold | 1,095 | 1,095 | 0.0% | 0 |
| Output the 0.55 gate rejects | 7,500 | 7,500 | 0.0% | 0 |
| **Total** | **176,092** | **20,582** | **about 88%** | **about 38,800 (estimate)** |

On the author's machine, transforming an output took tens of milliseconds and retrieving lines took under a millisecond. Run the benchmark to see figures for your hardware.

**What these numbers show:** On large, noisy outputs the delivered size drops by more than 80%, small outputs pass through untouched, and the stored copy matches the original text. For the 106,913 character log, the baseline model view has already lost its middle section. Detox keeps that section retrievable.

**What they don't show:** Whether agents finish tasks better with Detox. That has not been measured, and no claim about task success is made here.

---

## Compatibility

- Requires **Hermes Agent $\ge 0.19.0$**.
- Developed against Hermes Agent 0.19.0 and checked against the plugin validator on the current main branch.
- Registers three tools (`detox_inspect`, `detox_search`, `detox_status`), three hooks (`transform_tool_result`, `transform_terminal_output`, `on_session_reset`), and one slash command (`/detox`).
- If another plugin returns a string from `transform_tool_result` first, Hermes uses that string and Detox's result for that call is skipped.

---

## Known limitations

1. **Session IDs change when Hermes compacts a conversation.** `detox_inspect` and `detox_search` with an explicit evidence ID keep working across that change, because the ID itself is the authorization. A search without an ID covers only the current session, so evidence saved before a compaction is found by ID, not by unscoped search.
2. **Reports are built by pattern-based extractors.** They don't understand meaning, so an unusual log format may fall back to the generic report.
3. **Benchmarks use synthetic fixtures,** and token counts are estimates.
4. **Effect on agent task success has not been evaluated.**
5. **The evidence store is unencrypted,** as described under [Security and privacy](#security-and-privacy).

---

## Development

Run tests and benchmarks:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
python benchmarks/run_benchmark.py
hermes plugins validate . --install-deps
hermes plugins doctor . --ci
```

The test suite contains **74 tests** (73 passed, 1 skipped in the latest run).

The last two commands need a Hermes version that includes them. Use a current source install of Hermes Agent.

- `__init__.py`: Plugin registration, hooks, tools, slash command
- `config.py`: Typed settings with safe defaults
- `report.py`: Compact report builder
- `store.py`: SQLite evidence store
- `retention.py`: Age and size based cleanup
- `extractors/`: Content-aware extractors
- `detox_tools/`: `detox_inspect`, `detox_search`, `detox_status`
- `tests/`: Core, extractor, and safety tests
- `benchmarks/`: Benchmark runner
- `docs/`: Build reports for each stage
- `docs/demo/`: Live interactive demo, slides, and workflow script
- `plugin-catalog/`: Catalog entry for the Hermes plugin catalog

---

## Hackathon entry

Hermes Detox was built for the **Hermes Agent Plugin Hackathon**. It changes how Hermes handles tool output, using hooks, tools, and persistent local state.

- **Usefulness:** It protects context on the outputs that waste the most of it, and it recovers detail Hermes would otherwise drop.
- **Reliability:** It fails open, skips what it shouldn't touch, and is covered by automated tests for every fallback path.
- **Polish:** Zero dependencies, one-command install, configurable from `plugin.yaml`, and honest documentation of limits and risks.
- **Creativity:** Compaction and retrieval work together. The model reads a short report and keeps full access to the original.

---

## License

MIT. See [LICENSE](LICENSE).
