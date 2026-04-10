# GiantHoneyBee Architecture Plan

> Written: 2026-04-08 by Claude Opus 4.6 on Laptop Windows
> This is the detailed architecture. Must be reviewed and approved before coding begins.

---

## The Beautiful Insight

The existing Queen Bee has a method called `process_nectar(task) → result`. You give her a task (nectar), she splits it, distributes to workers, combines results, and gives you back an answer (honey).

The RajaBee does the EXACT SAME THING — but her "workers" are GiantQueens, not Worker Bees. From the RajaBee's perspective, each GiantQueen is just a black box that accepts a task and returns a result. She doesn't know (or care) that inside each GiantQueen, there's an entire sub-hierarchy doing the actual processing.

**Two types of Queens:**
- **GiantQueen** (named after *Apis dorsata*, the Giant Honey Bee) — a mid/upper-level coordinator. She splits tasks and combines results, but does NOT have Workers directly. She coordinates DwarfQueens (or other GiantQueens for deeper hierarchies).
- **DwarfQueen** (named after *Apis florea*, the Red Dwarf Honey Bee) — the lowest-level coordinator. She is the ONLY queen that has Workers directly under her. This is the existing QueenBee from HoneycombOfAI, wrapped in HTTP.

This means: **the RajaBee coordinates GiantQueens, who coordinate DwarfQueens, who have the actual Workers.**

And THIS is what makes it N-level: a GiantQueen's "worker" could be another RajaBee (who has GiantQueens under her, who have DwarfQueens under them, who have Workers). It's recursive. Turtles all the way down.

---

## Phase 1 Architecture: Localhost Test

### What we need to build:

**1. A simple HTTP wrapper around the existing Queen Bee (DwarfQueen)**

The existing Queen has `process_nectar(task) → result`. We wrap this in a tiny HTTP server — this wrapped Queen is a **DwarfQueen** because she has Workers directly under her:

```
POST http://localhost:5000/process
Body: {"task": "Summarize the history of Rome"}
Response: {"result": "Rome was founded in 753 BC..."}
```

This is a THIN wrapper. Maybe 20 lines of code. It just accepts a task over HTTP, calls `process_nectar()`, and returns the result. The Queen code stays COMPLETELY UNTOUCHED.

**2. The RajaBee class**

```python
class RajaBee:
    def __init__(self, model_name, giant_queen_endpoints):
        self.model_name = model_name      # AI model for splitting/combining
        self.giant_queen_endpoints = giant_queen_endpoints  # ["http://localhost:5000", "http://localhost:5001", ...]
        self.ai = OllamaClient()
    
    def process_royal_nectar(self, task):
        # Step 1: Split task into N major pieces (one per GiantQueen)
        pieces = self.split_task(task, len(self.giant_queen_endpoints))
        
        # Step 2: Send each piece to a different GiantQueen IN PARALLEL
        giant_queen_results = self.delegate_to_giant_queens(pieces)
        
        # Step 3: Combine all GiantQueens' results into one mega-answer
        royal_honey = self.combine_results(task, giant_queen_results)
        
        return royal_honey
```

**3. The splitting prompt (different from DwarfQueen's)**

The DwarfQueen splits into small subtasks ("write paragraph 1", "write paragraph 2").
The RajaBee splits into MAJOR COMPONENTS ("research the political history", "research the military history", "research the cultural history"). Each component is big enough that a GiantQueen (who delegates to DwarfQueens and their Workers) needs to handle it.

**4. The delegation (parallel HTTP calls)**

```python
def delegate_to_giant_queens(self, pieces):
    results = []
    with ThreadPoolExecutor(max_workers=len(self.giant_queen_endpoints)) as executor:
        futures = {}
        for i, piece in enumerate(pieces):
            endpoint = self.giant_queen_endpoints[i]
            future = executor.submit(self.send_to_giant_queen, endpoint, piece)
            futures[future] = endpoint
        
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
    
    return results
```

**5. The combining prompt (different from DwarfQueen's)**

The DwarfQueen combines subtask results into one answer.
The RajaBee combines GIANTQUEEN-LEVEL results into a MEGA answer. The prompt should be aware that each input is already a synthesized, complete section — not a raw subtask result.

---

## File Structure for Phase 1

```
GiantHoneyBee/
├── README.md                  (already created)
├── ARCHITECTURE.md            (this file)
├── raja_bee.py                (the RajaBee class)
├── queen_http_wrapper.py      (thin HTTP wrapper around existing Queen = DwarfQueen)
├── demo_raja.py               (Phase 1 demo: everything on localhost)
└── requirements.txt           (flask/fastapi, requests)
```

---

## How Phase 1 Demo Works (localhost, one machine)

### Setup:
1. Start Ollama with a small model (e.g., qwen2.5:1.5b)
2. Terminal 1: `python queen_http_wrapper.py --port 5000 --model qwen2.5:1.5b --workers 1`
   - Starts a DwarfQueen on port 5000 with 1 local worker
3. Terminal 2: `python queen_http_wrapper.py --port 5001 --model qwen2.5:1.5b --workers 1`
   - Starts a DwarfQueen on port 5001 with 1 local worker
4. Terminal 3: `python demo_raja.py --model llama3.2:3b --dwarf-queens http://localhost:5000,http://localhost:5001`
   - Starts the RajaBee, connected to both DwarfQueens

### What happens:
1. User types a complex task
2. RajaBee splits it into 2 major pieces (one per DwarfQueen)
3. RajaBee sends piece 1 to DwarfQueen on port 5000
4. RajaBee sends piece 2 to DwarfQueen on port 5001 (IN PARALLEL)
5. Each DwarfQueen splits her piece into subtasks for her worker(s)
6. Each DwarfQueen's worker(s) process subtasks
7. Each DwarfQueen combines her worker results into one answer
8. Each DwarfQueen sends her answer back to the RajaBee
9. RajaBee combines both DwarfQueens' answers into the MEGA answer
10. User sees the final result

### What this proves:
- Two-level hierarchy WORKS
- Parallel execution across DwarfQueens
- DwarfQueens don't know they're being orchestrated
- The existing HoneycombOfAI code is UNTOUCHED

---

## Making it N-Level (design principle, not Phase 1)

The key insight: the `queen_http_wrapper.py` exposes ANY process_nectar-compatible object as an HTTP endpoint. If we make RajaBee ALSO have a `process_nectar()` method, then a RajaBee can be wrapped in the same HTTP wrapper (becoming a GiantQueen to the level above), and ANOTHER RajaBee can call it.

```
RajaBee Level 3
  └── calls GiantQueen Level 2 (RajaBee via HTTP wrapper)
       └── calls DwarfQueen Level 1 (QueenBee via HTTP wrapper)
            └── calls Workers (local)
```

Each level is the same pattern: receive task → split → delegate → combine. The only difference is who you delegate to. GiantQueens delegate to other GiantQueens or DwarfQueens. DwarfQueens delegate to Workers.

---

## Resource-Aware Splitting (the "Report Up" Pattern)

### The problem (identified by Nir, 2026-04-08):
If the RajaBee naively splits work equally between GiantQueens, but GiantQueen A has 500 workers
and GiantQueen B has 10 workers, GiantQueen B becomes a bottleneck. The system is only as fast
as the slowest branch.

### The solution: "Report Up"
Before sending ANY tasks, the RajaBee asks each GiantQueen: "What do you have?"

Each GiantQueen (or DwarfQueen) exposes a capabilities endpoint:
```
GET /capabilities
Response: {"total_workers": 50, "models": ["qwen2.5:1.5b"], "avg_response_time": 3.2}
```

For N-level hierarchies, this aggregates naturally:
- Workers report capabilities to their DwarfQueen
- DwarfQueen aggregates and reports UP to her GiantQueen
- GiantQueen aggregates and reports UP to the RajaBee
- Each level only knows about its DIRECT children
- Aggregate numbers (total workers, total power) bubble up

The RajaBee then splits work PROPORTIONALLY:
- GiantQueen A has 90% of workers → gets 90% of the work
- GiantQueen B has 10% of workers → gets 10% of the work

### Why NOT a central registry?
A central database that knows all workers would be a single point of failure.
It destroys the resilience that makes our system valuable. Rejected.

### Why NOT "plans within plans" (top-down planning)?
The RajaBee would need to understand every worker at every level across all
GiantQueens and DwarfQueens — too much knowledge for one node. And if anything
changes (worker goes offline), the entire plan breaks. Rejected.

### Sequential tasks (socks-then-shoes problem):
Some tasks cannot be split into independent pieces. This is handled in the
PROMPT, not in the architecture. The splitting prompt says "split into
INDEPENDENT pieces." If the model determines the task is inherently sequential,
it should recognize this and either handle it without delegating, or split
into sequential phases run one after another (not in parallel).

---

## What We Do NOT Change

- queen_bee.py — UNTOUCHED
- worker_bee.py — UNTOUCHED
- All existing HoneycombOfAI files — UNTOUCHED
- BeehiveOfAI — UNTOUCHED

We only ADD new files in the GiantHoneyBee repo.

---

## Dependencies

- The GiantHoneyBee repo needs to IMPORT from HoneycombOfAI (specifically QueenBee, WorkerBee, OllamaClient)
- Options:
  a. Add HoneycombOfAI to Python path
  b. Symlink
  c. pip install from local path
  d. Just copy the needed files (simplest for Phase 1)

Recommended for Phase 1: option (a) — add HoneycombOfAI to path. Clean, no copying, no package management.

---

## Estimated Effort

- queen_http_wrapper.py: ~70 lines (DwarfQueen wrapper, includes /process AND /capabilities endpoints)
- raja_bee.py: ~200 lines (includes resource-aware proportional splitting across GiantQueens)
- demo_raja.py: ~30 lines
- Total: ~300 lines of new code

This is a one-session job for Sonnet 4.6.
