# Buzzing Calibration Bugs — Found During Phase 2 LAN Test (2026-04-11)

> **Found by:** Nir during Phase 2 LAN test on Desktop
> **Files affected:** `dwarf_queen_client.py`, `raja_bee.py`, `giant_queen_client.py` — all have `_run_calibration()`

**Status:** Bug 1 (simultaneous) — FIXED. Bug 2 (formula) — FIXED. Bug 3 (timing inconsistency) — ROOT CAUSE FOUND, FIX PROVEN, implementation pending.

---

## Bug 1: Simultaneous Calibration — FIXED

Calibration was sent to all workers at once. Workers sharing the same Ollama instance competed for it sequentially, so the first to arrive looked fast and the last looked slow. A scheduling artifact, not real performance.

**Fix:** Send calibration tasks sequentially — one at a time, wait for completion before sending the next.

---

## Bug 2: Speed Scoring Formula — FIXED

The old formula (`10 - 9 * ((elapsed - fastest) / (slowest - fastest))`) always gave the fastest worker 10 and the slowest 1, regardless of the actual time ratio. A worker 1% slower got the same score (1) as a worker 10x slower.

**Fix:** Proportional formula: `speed_score = 10.0 * (fastest / elapsed)`. A worker 2x slower gets 5.0, 3x slower gets 3.33, etc. Preserves actual ratios.

---

## Bug 3: LLM Backend Timing Inconsistency — ROOT CAUSE FOUND

### The problem

After fixing Bugs 1 and 2, identical workers on identical hardware still got wildly different calibration times. Sequential testing showed ~2x variation between runs.

### What we tried and what failed

| Attempt | Result | Why it failed |
|---------|--------|---------------|
| Warmup round (dummy "reply with one word" before all calibrations) | No change. 10.1s vs 5.1s still. | The warmup cached a DIFFERENT prompt. It did not flush the state that mattered. |
| Two-round reversed order (A,B then B,A, average times) | Partially helped (0.429 vs 0.571). | The inconsistency is not a consistent order bias — it's unpredictable noise. Averaging helped by accident, not by design. |
| Multiple rounds | Not tried. Would mask the problem, not fix it. |

### Root cause: LLM prompt evaluation caching

**Discovered through Google research + local experiment on 2026-04-11.**

All local LLM backends (Ollama, LM Studio, llama.cpp, vLLM) cache internal computations (KV cache, prompt token evaluation) from recent requests. When the SAME prompt arrives again, the backend skips most of the evaluation work — partial eval instead of full eval. This makes the second identical request much faster.

This is NOT GPU warmup. This is NOT model loading. This is the LLM backend recognizing it has already evaluated these specific tokens and reusing that work.

**Key insight from Nir:** A warmup with a DIFFERENT prompt doesn't help because it caches the WRONG tokens. You need a dummy question that OVERWRITES the cached state with something unrelated to the real calibration question. Then the real question gets a full, fair evaluation.

### Proof — local experiment on Laptop (RTX 5090)

```
=== TEST 1: Three sequential, NO reset between them ===
  Run 1: 3.90s    ← cold, full prompt evaluation
  Run 2: 1.36s    ← warm, partial eval (cached from Run 1)
  Run 3: 1.61s    ← warm

=== TEST 2: Three sequential, dummy reset BEFORE each ===
  Run 1: 1.38s    ← dummy absorbed cold start, real question gets fair eval
  Run 2: 1.30s    ← same
  Run 3: 1.53s    ← same
```

Confirmed with cold start (model unloaded between tests):

```
=== Cold start, NO reset ===
  Run 1: 3.08s    ← cold
  Run 2: 1.20s    ← cached
  Run 3: 1.13s    ← cached
  Run 4: 1.44s    ← cached

=== Cold start, dummy reset BEFORE each ===
  Run 1: 1.45s    ← consistent
  Run 2: 1.28s    ← consistent
  Run 3: 1.34s    ← consistent
  Run 4: 1.15s    ← consistent
```

**The dummy reset makes all runs consistent.** The ~3x penalty on the first run completely disappears.

### The fix: dummy reset before each calibration measurement

Before sending the real calibration question to each subordinate, send a short dummy question on a completely different topic (e.g., "What is the capital of Japan? Reply in one word."). This overwrites the backend's prompt cache with unrelated tokens. The real calibration question then gets a full, fair prompt evaluation — same for every worker.

### Why ONLY in calibration, NOT in real work

**Calibration** is about FAIR COMPARISON between workers. Cache advantages are unfair — they reflect test order, not hardware capability. The dummy reset levels the playing field.

**Real work** is about MAXIMUM PERFORMANCE. Cache advantages are a FEATURE during real work. Example from the MadHoney book: DwarfQueen sends robot simulation subtasks with incrementally different parameters (knee stiffness 0.70, 0.73, 0.76...). The LLM caches the robot context from the first subtask, making subsequent subtasks faster. This is free performance — killing it with dummy resets would sabotage throughput across thousands of workers.

**The rule:** Dummy reset in calibration (fairness). Let the cache work in production (performance).

### Scale implications

- **Same-machine workers** (our test setup): Both workers hit the same Ollama. The dummy reset is critical — without it, the second worker always benefits from the first's cached prompt evaluation.
- **Different-machine workers** (real mega-hive): Each worker has its own Ollama on its own machine. The prompt cache issue is less severe (no sharing), BUT workers that were recently active have warm Ollama state while idle workers are cold. The dummy reset normalizes all workers to a consistent state before measurement.
- **Multi-level hierarchies** (RajaBee → GiantQueen → DwarfQueen → Worker): Calibration happens at EVERY level. The dummy reset must happen at every level — RajaBee testing GiantQueens, GiantQueens testing DwarfQueens, DwarfQueens testing Workers.
- **Backend-agnostic:** This fix works with any LLM backend (Ollama, LM Studio, llama.cpp, vLLM) because all of them have some form of prompt/KV caching. No backend-specific API parameters needed.

### Files to fix

1. `GiantHoneyBee/dwarf_queen_client.py` — `_run_calibration()`
2. `GiantHoneyBee/raja_bee.py` — `_run_calibration()`
3. `GiantHoneyBee/giant_queen_client.py` — `_run_calibration()`

In each file, before each real calibration task, send a dummy question through the same KillerBee calibration API. Wait for the dummy to complete (discard result), then send the real question and measure time.
