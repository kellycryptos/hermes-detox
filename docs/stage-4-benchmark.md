# Stage 4 Benchmark Report: Performance, Token Reduction & Storage Round-Trip

**Status:** COMPLETE & BENCHMARKED (Realistic Baselines)  
**Benchmark Suite:** `benchmarks/run_benchmark.py`  
**Raw Results:** `docs/benchmark_results.json`  
**Overall Character Reduction:** **88.2%** (against realistic baselines)  
**Estimated Tokens Saved:** **38,823 tokens** (estimated as $\text{chars} / 4$)  
**Average Transformation Overhead:** **17.56 ms**  
**Average Inspection Retrieval Overhead:** **0.16 ms**  
**Storage Round-Trip Rate:** **100% (verbatim byte recovery)**  

---

## 1. Methodology & Baseline Rules

1. **Token Estimation:** All token figures are calculated using the standard approximation of $\text{chars} / 4$, explicitly labeled as estimates.
2. **Hermes Capped Baseline:** For the massive terminal output scenario, standard Hermes Agent enforces an inline truncation ceiling of 50,000 characters before the LLM sees it (dropping the middle 40–60%). The baseline is therefore capped at **50,000 characters**, while Detox captured the full **106,913 characters** un-truncated in SQLite.
3. **Storage Round-Trip:** Evaluates whether original lines (including error messages, line numbers, and markers) are retrievable byte-for-byte from SQLite via `detox_inspect`. This measures database fidelity, not LLM task completion.
4. **Boundary Scenarios Included:** In addition to high-compression payloads, the benchmark explicitly measures:
   - Short outputs (<6,000 chars) that pass through untouched.
   - Low-reducibility outputs rejected by the 0.55 compression ratio gate (fail-open bypass).
   - Secret-bearing outputs containing API keys.

---

## 2. Benchmark Results Matrix (9 Scenarios)

| Scenario | Captured Size | Baseline Size (chars / tokens est) | Delivered Size (chars / tokens est) | Reduction (%) | Estimated Tokens Saved | Transform Latency | Inspect Latency | Storage Round-Trip |
|---|---|---|---|---|---|---|---|---|
| **Pytest Test Suite** (3 fails, 42 pass) | 15,317 | 15,317 / 3,829 | 2,869 / 717 | **81.3%** | **3,112** | 56.16 ms | 0.16 ms | **PASS (verbatim)** |
| **C++ Build Log** (GCC/Clang, 4 files) | 9,902 | 9,902 / 2,475 | 1,894 / 473 | **80.9%** | **2,002** | 4.01 ms | 0.14 ms | **PASS (verbatim)** |
| **JSON API Payload** (50 records) | 29,923 | 29,923 / 7,480 | 1,973 / 493 | **93.4%** | **6,987** | 6.82 ms | 0.12 ms | **PASS (verbatim)** |
| **Filesystem Listing** (580 files, tree) | 15,155 | 15,155 / 3,788 | 671 / 167 | **95.6%** | **3,621** | 12.33 ms | 0.13 ms | **PASS (verbatim)** |
| **Server Trace Log** (420 lines) | 35,448 | 35,448 / 8,862 | 2,425 / 606 | **93.2%** | **8,256** | 25.15 ms | 0.15 ms | **PASS (verbatim)** |
| **Massive Terminal Log** (>50k cap) | 106,913 | 50,000 / 12,500 | 1,341 / 335 | **97.3%** | **12,165** | 41.74 ms | 0.18 ms | **PASS (verbatim)** |
| **Short Output Below Threshold** (<6k) | 1,095 | 1,095 / 273 | 1,095 / 273 | **0.0%** | **0** | 0.01 ms | 0.00 ms | **N/A (passthrough)** |
| **Low-Reducibility Payload** (0.55 gate) | 7,500 | 7,500 / 1,875 | 7,500 / 1,875 | **0.0%** | **0** | 2.77 ms | 0.00 ms | **N/A (gate bypass)** |
| **Output with Secret Strings** (`sk-ant-`) | 11,775 | 11,775 / 2,943 | 1,055 / 263 | **91.0%** | **2,680** | 9.07 ms | 0.17 ms | **PASS (verbatim)** |
| **TOTAL / OVERALL** | **233,028** | **176,115 / 44,025** | **20,823 / 5,202** | **88.2%** | **38,823** | **17.56 ms** | **0.16 ms** | **100% (7/7 PASS)** |

---

## 3. Key Observations

1. **Realistic Baseline Impact:** When factoring in the Hermes 50,000-character truncation ceiling as the baseline for large terminal outputs, overall reduction is **88.2%** (saving an estimated **38,823 tokens**), while Detox preserves the full 106k payload un-truncated.
2. **Loss-Free Middle Recovery:** In standard Hermes, line 750 of the massive terminal log (at byte offset ~53,400) would have been irreversibly dropped by inline truncation. Detox stored the full 106,913 characters before truncation and recovered line 750 in 0.18 ms with 100% byte fidelity.
3. **Safe Passthrough on Low Reducibility:** Outputs that do not benefit from compression (such as high-entropy payloads or single long lines) are caught by the 0.55 ratio gate in 2.77 ms and delivered to the model untouched without risk of report ballooning.
4. **Sub-Millisecond Inspection:** `detox_inspect` retrieves exact 1-based line slices from local SQLite in an average of **0.16 ms**.
