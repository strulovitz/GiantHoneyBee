"""
DwarfQueen Client -- Lowest-Level Coordinator (KillerBee API)
=============================================================
Named after Apis florea (Red Dwarf Honey Bee).

The DwarfQueen is the LOWEST-level coordinator -- the only queen that
creates subtasks for Workers. She receives components from GiantQueens,
splits them into subtasks, and posts them to KillerBee for Workers to claim.

All communication goes through the KillerBee website API.
No direct HTTP between bees. No in-process Workers.

Workflow:
1. Login to KillerBee
2. Poll for assigned work (components from GiantQueens)
3. When a component arrives: use local Ollama to split into subtasks
4. Post subtasks to KillerBee (Workers will claim these)
5. Poll until all subtasks have results
6. Use local Ollama to combine subtask results
7. Post combined result to KillerBee

Hierarchy: RajaBee -> GiantQueens -> DwarfQueens -> Workers
"""

import sys
import os
import time
import json
import argparse

# Add HoneycombOfAI to path for AI backend
HONEYCOMB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'HoneycombOfAI')
sys.path.insert(0, HONEYCOMB_PATH)

from ollama_client import OllamaClient
from killerbee_client import KillerBeeClient


def print_banner(text: str, char: str = "="):
    line = char * 60
    print(f"\n{line}")
    print(f"  {text}")
    print(f"{line}")


class DwarfQueenClient:
    """
    DwarfQueen -- Lowest-level coordinator.

    Polls KillerBee for assigned components, splits them into subtasks
    for Workers, waits for results, combines them.
    """

    def __init__(self, server_url: str, swarm_id: int,
                 username: str, password: str,
                 model_name: str = "qwen2.5:1.5b",
                 ollama_url: str = "http://localhost:11434",
                 poll_interval: int = 5):
        self.server_url = server_url
        self.swarm_id = swarm_id
        self.model_name = model_name
        self.poll_interval = poll_interval
        self.member_id = None
        self.subordinate_type = "worker"
        self.rediscovery_interval = 10
        self._poll_count = 0

        # Buzzing system: subordinates and their fractions
        self.subordinates = []   # list of subordinate dicts from KillerBee
        self.fractions = []      # list of {member_id, name, fraction} dicts
        self._last_known_capacities = {}  # member_id -> capacity

        self.kb = KillerBeeClient(server_url, username, password)
        self.ai = OllamaClient(base_url=ollama_url)

    def start(self):
        """Login, register, and start the main loop."""
        print_banner("DwarfQueen -- Lowest-Level Coordinator")
        print(f"  Server:    {self.server_url}")
        print(f"  Swarm:     {self.swarm_id}")
        print(f"  Model:     {self.model_name}")
        print(f"  Username:  {self.kb.username}")

        if not self.ai.is_available():
            print("\n  [ERROR] Cannot connect to Ollama! Is it running?")
            return False
        print(f"  Ollama:    Connected ({self.ai.backend_name()})")

        try:
            self.kb.login()
            print(f"  KillerBee: Logged in (user_id={self.kb.user_id})")
        except Exception as e:
            print(f"\n  [ERROR] Cannot login to KillerBee: {e}")
            return False

        try:
            reg_data = self.kb.register_member(
                self.swarm_id, "dwarf_queen", self.model_name
            )
            self.member_id = reg_data.get("member_id", self.kb.user_id)
            print(f"  Registered as DwarfQueen (member_id={self.member_id})")
        except Exception as e:
            print(f"  [WARN] Registration: {e}")
            self.member_id = self.kb.user_id

        # ── Buzzing: Discover, Calibrate, Get Fractions ──────────────
        self._buzzing_cycle(self.subordinate_type)
        # ─────────────────────────────────────────────────────────────

        print_banner("DwarfQueen is RUNNING. Polling for work...")
        self._main_loop()
        return True

    # ── Buzzing: Discovery, Calibration, Fractions ─────────────────

    def _buzzing_cycle(self, subordinate_type: str):
        """Run full Buzzing cycle: discover, calibrate, get fractions."""
        print_banner("BUZZING: Discovering & Calibrating Subordinates")
        old_count = len(self.subordinates)
        self._discover_and_claim_subordinates(subordinate_type)
        if self.subordinates:
            needs_recalibration = False

            if len(self.subordinates) > old_count or not self.fractions:
                needs_recalibration = True
                print("  [BUZZING] New subordinates or first calibration.")

            if not needs_recalibration:
                try:
                    current_fractions = self.kb.get_fractions(self.member_id)
                    for sub in current_fractions.get("subordinates", []):
                        sub_id = sub.get("member_id")
                        sub_cap = sub.get("capacity") or 0
                        old_cap = self._last_known_capacities.get(sub_id, sub_cap)
                        if abs(sub_cap - old_cap) > 0.01:
                            print(f"  [BUZZING] {sub.get('username', sub_id)}'s "
                                  f"capacity changed: {old_cap:.1f} -> {sub_cap:.1f}")
                            needs_recalibration = True
                            break
                except Exception:
                    pass

            if needs_recalibration:
                self._run_calibration()
                self._fetch_fractions()
                try:
                    current = self.kb.get_fractions(self.member_id)
                    for sub in current.get("subordinates", []):
                        self._last_known_capacities[sub.get("member_id")] = sub.get("capacity") or 0
                except Exception:
                    pass
            else:
                print("  [BUZZING] No changes. Fractions unchanged.")
        else:
            print("  [BUZZING] No subordinates found yet. "
                  "Will check again periodically.")

    def _discover_and_claim_subordinates(self, subordinate_type: str):
        """Find unassigned members and claim them. Also load existing."""
        try:
            existing = self.kb.get_subordinates(self.member_id)
            if existing:
                print(f"  [BUZZING] Found {len(existing)} existing "
                      f"subordinate(s)")
                for sub in existing:
                    sub_id = sub.get("member_id") or sub.get("id")
                    sub_name = sub.get("username", f"member-{sub_id}")
                    print(f"    - {sub_name} (member_id={sub_id})")
                self.subordinates = existing
        except Exception as e:
            print(f"  [BUZZING] Could not fetch existing subordinates: {e}")

        try:
            unassigned = self.kb.get_unassigned_members(
                self.swarm_id, subordinate_type
            )
            if unassigned:
                print(f"  [BUZZING] Found {len(unassigned)} unassigned "
                      f"{subordinate_type}(s) to claim")
                for member in unassigned:
                    m_id = member.get("member_id") or member.get("id")
                    m_name = member.get("username", f"member-{m_id}")
                    try:
                        self.kb.claim_subordinate(self.member_id, m_id)
                        print(f"    - Claimed {m_name} (member_id={m_id})")
                        self.subordinates.append(member)
                    except Exception as e:
                        print(f"    - Failed to claim {m_name}: {e}")
            else:
                print(f"  [BUZZING] No unassigned {subordinate_type}s found")
        except Exception as e:
            print(f"  [BUZZING] Could not fetch unassigned members: {e}")

        print(f"  [BUZZING] Total subordinates: {len(self.subordinates)}")

    def _run_calibration(self):
        """Generate a test, send to all subordinates, score them."""
        print_banner("BUZZING: Running Calibration Test", char="-")

        print("  [BUZZING] Generating calibration test question...")
        test_question = self.ai.ask(
            prompt=("Generate a short test question that requires a detailed "
                    "2-paragraph answer about any topic. Just output the "
                    "question, nothing else."),
            model=self.model_name,
            temperature=0.7
        ).strip()
        print(f"  [BUZZING] Calibration question: {test_question[:100]}...")

        calibration_tasks = {}
        for sub in self.subordinates:
            sub_id = sub.get("member_id") or sub.get("id")
            sub_name = sub.get("username", f"member-{sub_id}")
            try:
                cal_data = self.kb._request(
                    "POST", f"/api/member/{sub_id}/calibration", {
                        "task": test_question,
                        "component_type": "calibration"
                    }
                )
                comp_id = cal_data.get("component_id") or cal_data.get("id")
                calibration_tasks[sub_id] = {
                    "component_id": comp_id,
                    "name": sub_name,
                    "start_time": time.time()
                }
                print(f"  [BUZZING] Sent calibration to {sub_name} "
                      f"(component_id={comp_id})")
            except Exception as e:
                print(f"  [BUZZING] Failed to send calibration to "
                      f"{sub_name}: {e}")

        if not calibration_tasks:
            print("  [BUZZING] No calibration tasks sent. Skipping.")
            return

        print("  [BUZZING] Waiting for all subordinates to complete "
              "calibration...")
        results = {}
        max_wait = 600
        waited = 0

        while waited < max_wait:
            time.sleep(self.poll_interval)
            waited += self.poll_interval

            all_done = True
            for sub_id, cal_info in calibration_tasks.items():
                if sub_id in results:
                    continue
                try:
                    comp_resp = self.kb._request(
                        "GET",
                        f"/api/component/{cal_info['component_id']}/status"
                    )
                    if (comp_resp.get("status") == "completed"
                            and comp_resp.get("result")):
                        elapsed = time.time() - cal_info["start_time"]
                        results[sub_id] = {
                            "result": comp_resp["result"],
                            "elapsed_time": elapsed,
                            "name": cal_info["name"]
                        }
                        print(f"  [BUZZING] {cal_info['name']} completed "
                              f"in {elapsed:.1f}s")
                    else:
                        all_done = False
                except Exception as e:
                    all_done = False

            if all_done:
                break

            completed = len(results)
            total = len(calibration_tasks)
            print(f"  [BUZZING] Waiting... {completed}/{total} done "
                  f"({waited}s elapsed)", end="\r")

        if not results:
            print("  [BUZZING] No calibration results received. Skipping.")
            return

        print_banner("BUZZING: Scoring Subordinates", char="-")

        times = {sid: r["elapsed_time"] for sid, r in results.items()}
        fastest = min(times.values())
        slowest = max(times.values())

        for sub_id, r in results.items():
            elapsed = r["elapsed_time"]
            if slowest == fastest:
                speed_score = 10.0
            else:
                speed_score = 10.0 - 9.0 * (
                    (elapsed - fastest) / (slowest - fastest)
                )
            speed_score = round(max(1.0, min(10.0, speed_score)), 1)

            quality_prompt = (
                f"Rate the following answer from 1 to 10 for completeness "
                f"and accuracy. The question was: \"{test_question}\"\n\n"
                f"Answer to rate:\n{r['result']}\n\n"
                f"Reply with ONLY a single number from 1 to 10, nothing else."
            )
            quality_text = self.ai.ask(
                prompt=quality_prompt,
                model=self.model_name,
                temperature=0.1
            ).strip()

            try:
                quality_score = float(
                    ''.join(c for c in quality_text if c.isdigit() or c == '.')
                )
                quality_score = max(1.0, min(10.0, quality_score))
            except (ValueError, TypeError):
                quality_score = 5.0

            quality_score = round(quality_score, 1)
            buzzing = round(speed_score * quality_score, 1)

            print(f"  [BUZZING] {r['name']}: speed={speed_score}, "
                  f"quality={quality_score}, buzzing={buzzing}")

            try:
                self.kb.report_buzzing(
                    sub_id, speed_score, quality_score, self.member_id
                )
                print(f"  [BUZZING] Reported buzzing for {r['name']}")
            except Exception as e:
                print(f"  [BUZZING] Failed to report buzzing for "
                      f"{r['name']}: {e}")

        try:
            self.kb.recalculate_member(self.member_id)
            print("  [BUZZING] Recalculated capacity and fractions")
        except Exception as e:
            print(f"  [BUZZING] Recalculate failed: {e}")

    def _fetch_fractions(self):
        """Fetch fractions from KillerBee and store locally."""
        try:
            fractions_data = self.kb.get_fractions(self.member_id)
            self.fractions = fractions_data.get("subordinates", [])
            if self.fractions:
                print_banner("BUZZING: Fractions for Splitting", char="-")
                for f in self.fractions:
                    name = f.get("username", f.get("name", "unknown"))
                    frac = f.get("fraction") or 0
                    print(f"  {name}: {frac:.3f}")
                print(f"  Total: {sum((f.get('fraction') or 0) for f in self.fractions):.3f}")
            else:
                print("  [BUZZING] No fractions received. "
                      "Will use equal splitting.")
        except Exception as e:
            print(f"  [BUZZING] Could not fetch fractions: {e}")

    # ── Main Loop ─────────────────────────────────────────────────────

    def _main_loop(self):
        """Poll KillerBee for available components to claim and process."""
        while True:
            try:
                # Periodically re-discover subordinates
                self._poll_count += 1
                if self._poll_count % self.rediscovery_interval == 0:
                    self._buzzing_cycle(self.subordinate_type)

                # Don't accept work until we have subordinates
                if not self.subordinates:
                    print(f"  Waiting for Workers to join... "
                          f"(checking every {self.poll_interval}s)", end="\r")
                    self._buzzing_cycle(self.subordinate_type)
                    time.sleep(self.poll_interval)
                    continue

                # First check for work already assigned to us
                work = self.kb.get_my_work(self.member_id)
                if work:
                    for component in work:
                        comp_id = component.get("id") or component.get("component_id")
                        task = component.get("task", "")
                        original_task = component.get("original_task", task)
                        status = component.get("status", "")
                        if status in ("pending", "assigned", ""):
                            print(f"\n  [COMPONENT {comp_id}] Assigned to me: "
                                  f"{task[:80]}...")
                            self._process_component(comp_id, task, original_task)
                else:
                    # Check for unclaimed components we can claim
                    available = self.kb.get_available_components(self.swarm_id)
                    if available:
                        for component in available:
                            comp_id = component.get("id")
                            task = component.get("task", "")
                            original_task = component.get("original_task", task)
                            try:
                                self.kb.claim_component(comp_id, self.member_id)
                                print(f"\n  [COMPONENT {comp_id}] Claimed: "
                                      f"{task[:80]}...")
                                self._process_component(comp_id, task, original_task)
                                break  # One at a time
                            except Exception as e:
                                print(f"  [COMPONENT {comp_id}] Could not claim: {e}")
                                continue
                    else:
                        print(f"  Polling... no work available. "
                              f"({len(self.subordinates)} Workers, "
                              f"waiting {self.poll_interval}s)", end="\r")
            except Exception as e:
                print(f"  [ERROR] Polling failed: {e}")

            time.sleep(self.poll_interval)

    def _process_component(self, component_id: int, task: str, original_task: str = ""):
        """Process a component: split into subtasks for Workers."""
        start_time = time.time()
        original_task = original_task or task

        # Step 1: Claim the component
        try:
            self.kb.claim_component(component_id, self.member_id)
            print(f"  [COMPONENT {component_id}] Claimed")
        except Exception as e:
            print(f"  [COMPONENT {component_id}] [WARN] Claim: {e}")

        # Step 2: Split into subtasks using local Ollama
        print(f"  [COMPONENT {component_id}] Splitting into subtasks "
              f"for Workers...")
        subtasks = self._split_into_subtasks(task, original_task)
        print(f"  [COMPONENT {component_id}] Split into "
              f"{len(subtasks)} subtasks")

        for i, st in enumerate(subtasks):
            print(f"    Subtask {i+1}: {st[:70]}...")

        # Step 3: Post subtasks to KillerBee (Workers will claim these)
        children_data = [{"task": st, "component_type": "subtask"} for st in subtasks]
        try:
            split_result = self.kb.split_component(component_id, children_data)
            print(f"  [COMPONENT {component_id}] Subtasks posted "
                  f"(Workers can now claim them)")
        except Exception as e:
            print(f"  [COMPONENT {component_id}] [ERROR] "
                  f"Failed to post subtasks: {e}")
            return

        # Step 4: Wait for all subtasks to have results
        print(f"  [COMPONENT {component_id}] Waiting for Workers...")
        child_results = self._wait_for_children(component_id, split_result)

        if not child_results:
            print(f"  [COMPONENT {component_id}] [ERROR] "
                  f"No subtask results received")
            return

        # Step 5: Combine results
        print(f"  [COMPONENT {component_id}] Combining "
              f"{len(child_results)} Worker results...")
        combined = self._combine_results(task, original_task, child_results)

        processing_time = time.time() - start_time

        # Step 6: Post combined result
        try:
            self.kb.post_component_result(
                component_id, combined, processing_time
            )
            print(f"  [COMPONENT {component_id}] COMPLETE in "
                  f"{processing_time:.1f}s")
        except Exception as e:
            print(f"  [COMPONENT {component_id}] [ERROR] "
                  f"Failed to post result: {e}")

    def _split_into_subtasks(self, task: str, original_task: str = "") -> list:
        """Use local Ollama to split a component into subtasks for Workers.

        If fractions are available from Buzzing calibration, the number of
        subtasks matches the number of Workers, and each is sized
        proportionally by fraction.
        """
        original_task = original_task or task
        num_workers = len(self.fractions) if self.fractions else None

        if num_workers and num_workers >= 2:
            fraction_lines = []
            for i, f in enumerate(self.fractions):
                name = f.get("username", f.get("name", f"Worker {i+1}"))
                frac = f.get("fraction", round(1.0 / num_workers, 2))
                fraction_lines.append(
                    f"Subtask {i+1} should cover about {frac:.2f} "
                    f"of the total work (for {name})"
                )
            fraction_instructions = "\n".join(fraction_lines)

            prompt = f"""You are a team lead splitting a task into exactly {num_workers} small, specific subtasks that individual workers can complete independently.

CRITICAL CONTEXT: The ORIGINAL QUESTION that started this whole process was:
"{original_task}"

Your specific component to split into subtasks is: {task}

SIZE EACH SUBTASK PROPORTIONALLY:
{fraction_instructions}

A subtask with fraction 0.60 should be about 3x as much work as one with fraction 0.20.
Larger fractions = broader scope. Smaller fractions = narrower, more focused.

RULES:
- Each subtask must be SMALL and SPECIFIC (a single focused question or action)
- Each subtask must be INDEPENDENT (worker doesn't need other results)
- Together they must fully cover YOUR component
- Every subtask MUST stay relevant to the ORIGINAL QUESTION above
- Do NOT drift into unrelated topics

The task to split: {task}

Return ONLY a JSON array of exactly {num_workers} strings.

Your JSON array:"""
        else:
            prompt = f"""You are a team lead splitting a task into 2-4 small, specific subtasks that individual workers can complete independently.

CRITICAL CONTEXT: The ORIGINAL QUESTION that started this whole process was:
"{original_task}"

Your specific component to split into subtasks is: {task}

RULES:
- Each subtask must be SMALL and SPECIFIC (a single focused question or action)
- Each subtask must be INDEPENDENT (worker doesn't need other results)
- Together they must fully cover YOUR component
- Every subtask MUST stay relevant to the ORIGINAL QUESTION above
- Do NOT drift into unrelated topics — if the original question asks for pros and cons, the subtasks should be about pros and cons

The task to split: {task}

Return ONLY a JSON array of strings. Example: ["subtask 1", "subtask 2", "subtask 3"]

Your JSON array:"""

        result = self.ai.ask_for_json_list(
            prompt=prompt,
            model=self.model_name,
            temperature=0.3
        )

        if not result or len(result) < 2:
            result = [task]

        return result

    def _wait_for_children(self, component_id: int,
                           split_result: dict) -> list:
        """Poll until all children (subtasks) have results."""
        max_wait = 3600
        waited = 0

        while waited < max_wait:
            time.sleep(self.poll_interval)
            waited += self.poll_interval

            try:
                children = self.kb.get_children(component_id)
                if not children:
                    continue

                all_done = True
                completed_results = []

                for child in children:
                    if child.get("result"):
                        completed_results.append(child)
                    else:
                        all_done = False

                if all_done and completed_results:
                    print(f"  [COMPONENT {component_id}] All "
                          f"{len(completed_results)} subtasks completed "
                          f"after {waited}s")
                    return completed_results

                print(f"  [COMPONENT {component_id}] Waiting... "
                      f"{len(completed_results)}/{len(children)} done "
                      f"({waited}s)", end="\r")

            except Exception as e:
                print(f"  [COMPONENT {component_id}] [WARN] Poll error: {e}")

        print(f"  [COMPONENT {component_id}] [TIMEOUT] Waited {max_wait}s")
        return []

    def _combine_results(self, component_task: str, original_task: str,
                         child_results: list) -> str:
        """Use local Ollama to combine Worker results."""
        formatted = ""
        for i, cr in enumerate(child_results):
            task_desc = cr.get("task", f"Subtask {i+1}")
            result_text = cr.get("result", "[No result]")
            formatted += f"\n--- Worker {i+1}: {task_desc[:60]} ---\n"
            formatted += f"{result_text}\n"

        prompt = f"""You are combining results from {len(child_results)} workers into one coherent answer.

ORIGINAL QUESTION (what the user actually asked): {original_task}

YOUR SPECIFIC COMPONENT was: {component_task}

Worker results:
{formatted}

Combine into ONE clear, complete answer that addresses YOUR COMPONENT in the context of the ORIGINAL QUESTION.
Stay focused on what was actually asked. Integrate smoothly, remove redundancy, keep all important details.

Your combined answer:"""

        return self.ai.ask(
            prompt=prompt,
            model=self.model_name,
            temperature=0.5
        )


def main():
    parser = argparse.ArgumentParser(
        description="DwarfQueen -- Lowest-level coordinator. "
                    "Connects to KillerBee website API."
    )
    parser.add_argument('--server', type=str, required=True,
                        help='KillerBee server URL')
    parser.add_argument('--swarm-id', type=int, required=True,
                        help='Swarm ID to join')
    parser.add_argument('--username', type=str, required=True,
                        help='Username for KillerBee login')
    parser.add_argument('--password', type=str, required=True,
                        help='Password for KillerBee login')
    parser.add_argument('--model', type=str, default='qwen2.5:1.5b',
                        help='Ollama model name (default: qwen2.5:1.5b)')
    parser.add_argument('--ollama-url', type=str,
                        default='http://localhost:11434',
                        help='Ollama API URL')
    parser.add_argument('--poll-interval', type=int, default=5,
                        help='Seconds between polls (default: 5)')
    args = parser.parse_args()

    queen = DwarfQueenClient(
        server_url=args.server,
        swarm_id=args.swarm_id,
        username=args.username,
        password=args.password,
        model_name=args.model,
        ollama_url=args.ollama_url,
        poll_interval=args.poll_interval
    )

    queen.start()


if __name__ == '__main__':
    main()
