# Golden Rules for Claude Code

## RULE #1: NO SHORTCUTS. NO REWARD HACKING. EVER.

Never take shortcuts that make a demo "look like it works" while bypassing the real architecture. If the real-world design says Workers are separate machines, then Workers MUST be separate machines in testing. Do NOT simulate them as in-process objects, local threads, or function calls just to get a quick result.

If something is supposed to be distributed, it must BE distributed.
If something is supposed to be a separate machine, it must BE a separate machine (or a real VM with its own OS, its own IP, its own processes).
If something is supposed to communicate over a network, it must communicate over a REAL network.

Faking the architecture to pass a test faster is REWARD HACKING. It produces results that look correct but prove nothing. It wastes the user's time by creating false confidence.

### What this means concretely:
- Workers are SEPARATE MACHINES. They connect to Queens over the network via the BeehiveOfAI website API. They are NEVER in-process Python objects pretending to be machines.
- Queens are SEPARATE MACHINES. They connect to RajaBees over HTTP.
- If a test requires 6 machines, use 6 machines (or 6 VMs). Do NOT run everything in one process on one machine and call it "distributed."

### If the real implementation is hard:
- Say it's hard. Explain why. Propose a plan.
- Do NOT silently simplify the architecture to make it easier.
- The user would rather wait a week for a real test than get a fake result in an hour.
