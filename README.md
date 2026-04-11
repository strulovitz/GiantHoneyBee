# 🐝 Giant Honey Bee

**The Hierarchical Distributed AI Software — RajaBee, GiantQueen, DwarfQueen, and WorkerBee Orchestration**

---

## What Is This?

Giant Honey Bee is the software that enables hierarchical AI hives — where a RajaBee (king of the bees) coordinates multiple GiantQueens, who coordinate DwarfQueens, each commanding their own hive of Worker Bees. It is the next level above [Honeycomb Of AI](https://github.com/strulovitz/HoneycombOfAI), adding unlimited vertical scaling through nested hive layers.

If Honeycomb Of AI turns one computer into a bee, Giant Honey Bee turns an entire swarm of hives into one mind.

---

## The Hierarchy

```
Worker Bee → DwarfQueen → GiantQueen → RajaBee
```

### 👑 RajaBee
The king of the bees — named after **Megachile pluto** (Wallace's Giant Bee), the largest bee species in the world. The RajaBee receives a complex task, splits it into pieces, and delegates each piece to a GiantQueen. Results flow back up the chain: Workers → DwarfQueen → GiantQueen → RajaBee → final answer.

### 🐝 GiantQueen
Named after **Apis dorsata** (Giant Honey Bee). The mid/upper-level coordinator. She splits tasks and combines results, but does NOT have Workers directly. She coordinates DwarfQueens (or other GiantQueens for deeper hierarchies). A GiantQueen is actually a RajaBee wrapped in an HTTP endpoint, so higher levels see her as just another node.

### 🐝 DwarfQueen
Named after **Apis florea** (Red Dwarf Honey Bee). The lowest-level coordinator — the ONLY queen that has Workers directly under her. This is the existing QueenBee from Honeycomb Of AI, wrapped in HTTP via `queen_http_wrapper.py`. She doesn't need to know she's being orchestrated. She receives a task, splits it, distributes to her Workers, combines results. Exactly as before.

### 💻 WorkerBee
The same Worker Bee from Honeycomb Of AI — unchanged. Receives a subtask, processes it with a local AI model, returns the result.

---

## How It Scales

The system is modular — any number of levels:

- **2 levels:** RajaBee → DwarfQueens → Workers (tested on localhost — see KillerBee/EXPERIMENT_LOG.md)
- **3 levels:** RajaBee → GiantQueens → DwarfQueens → Workers (designed, not yet tested)
- **N levels:** Unlimited depth. The only limit is available hardware, never the software.

---

## Relationship to Existing Projects

| Project | Role |
|---------|------|
| [HoneycombOfAI](https://github.com/strulovitz/HoneycombOfAI) | Level 1 — single hive (Queen + Workers) |
| **GiantHoneyBee** (this repo) | Level 2+ — hierarchical orchestration layer |
| [KillerBee](https://github.com/strulovitz/KillerBee) | Website/server — manages the hierarchy |
| [BeehiveOfAI](https://github.com/strulovitz/BeehiveOfAI) | Level 1 website/marketplace |

---

## Free. Open Source. Forever.

Like everything in the beehive ecosystem, this software is completely free and open source. No subscription. No license fee. No vendor lock-in. Your data never leaves your building.
