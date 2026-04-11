# Buzzing Calibration Bugs — Found During Phase 2 LAN Test (2026-04-11)

> **Found by:** Nir during Phase 2 LAN test on Desktop
> **Must fix before:** Rerunning Phase 2 LAN test
> **Files to fix:** `dwarf_queen_client.py` and `raja_bee.py` — both have `_run_calibration()` with the same two bugs

---

## Bug 1: Simultaneous Calibration Causes False Speed Differences

### What happened

During Buzzing calibration, the DwarfQueen sent the calibration task to BOTH workers **at the same time**. Both workers are on the **same machine** (Desktop), hitting the **same local Ollama instance**. Ollama processes requests **sequentially** (one at a time). 

Result:
- worker_alpha finished in **5.0s** (got Ollama immediately)
- worker_bravo finished in **10.1s** (waited ~5s in Ollama's queue, then processed for ~5s)

The 2x time difference is a **scheduling artifact**, NOT a real performance difference. They are identical workers on identical hardware with the identical model.

### The fix

Calibration tasks must be sent **SEQUENTIALLY**, not simultaneously. The flow should be:

1. Send calibration to worker_alpha
2. **Wait for worker_alpha to complete**
3. Send calibration to worker_bravo
4. **Wait for worker_bravo to complete**

This way each worker gets exclusive Ollama access and the timing reflects **actual processing speed**, not queue position.

### Where in the code

In `_run_calibration()`, the current code posts calibration tasks to ALL subordinates in a loop without waiting:

```python
for sub in self.subordinates:
    # Posts calibration task immediately — all hit Ollama at once
    cal_data = self.kb._request("POST", f"/api/member/{sub_id}/calibration", ...)
    calibration_tasks[sub_id] = {"component_id": comp_id, "start_time": time.time()}
```

Then it waits for all results in a separate polling loop. This means all subordinates are processing concurrently, competing for the same Ollama.

**Fix:** Send calibration to one subordinate, poll until it completes, record time. Then send to the next. Each subordinate gets a fair, uncontested measurement.

---

## Bug 2: Speed Scoring Formula Is Broken

### What happened

The speed scoring formula uses linear interpolation where the fastest always gets 10 and the slowest always gets 1, **regardless of the actual time ratio**:

```python
speed_score = 10.0 - 9.0 * ((elapsed - fastest) / (slowest - fastest))
```

With only 2 workers:
- Fastest → 10.0 (always)
- Slowest → 1.0 (always)

This means:
- If one takes 5.0s and the other takes 5.1s → scores are 10 and 1 (absurd!)
- If one takes 5.0s and the other takes 10.0s → scores are 10 and 1 (a 2x difference becomes 10x)
- If one takes 5.0s and the other takes 50.0s → scores are 10 and 1 (a 10x difference is also 10x)

The formula **destroys all information about the actual ratio** between speeds.

In our test: worker_alpha (5.0s) got buzzing 60.0, worker_bravo (10.1s) got buzzing 6.0. Fractions: 0.909 vs 0.091. That means worker_alpha gets **10x more work** than worker_bravo, even though it's only **2x faster**. The fractions should have been roughly 0.667 vs 0.333.

### The fix

Speed score should be **proportional to actual times**:

```python
speed_score = 10.0 * (fastest / elapsed)
```

Examples with this formula:
- Same speed as fastest → `10 * (5/5)` = **10.0**
- 2x slower than fastest → `10 * (5/10)` = **5.0**
- 3x slower → `10 * (5/15)` = **3.33**
- 10x slower → `10 * (5/50)` = **1.0**

This preserves the actual performance ratio. Two workers that are 2x apart in speed will get buzzings that are 2x apart (assuming same quality), leading to fractions that are 2:1 — which is correct.

### Where in the code

In `_run_calibration()`, the scoring section:

```python
# Current (broken):
if slowest == fastest:
    speed_score = 10.0
else:
    speed_score = 10.0 - 9.0 * ((elapsed - fastest) / (slowest - fastest))

# Should be:
speed_score = 10.0 * (fastest / elapsed)
```

The `min(10.0, max(1.0, ...))` clamping can stay as a safety net.

---

## Both bugs exist in both files

1. **GiantHoneyBee/dwarf_queen_client.py** — `_run_calibration()` method (lines ~196-338)
2. **GiantHoneyBee/raja_bee.py** — `_run_calibration()` method (lines ~209-363)

Both files have identical calibration logic and need the same two fixes.

---

## After fixing

1. Push fixes to GitHub
2. Desktop does `git pull` in GiantHoneyBee
3. Kill all 3 Desktop bees (Ctrl+C in each terminal)
4. Laptop kills RajaBee if running
5. Laptop re-seeds KillerBee database (fresh start)
6. Restart all bees and rerun Phase 2 LAN test
