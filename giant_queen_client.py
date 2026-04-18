"""
GiantQueen Client -- Mid-Level Coordinator (KillerBee API)
==========================================================
Named after Apis dorsata (Giant Honey Bee).

The GiantQueen is a mid-level coordinator. She receives components from
the RajaBee (or a higher GiantQueen), splits them into sub-components
for DwarfQueens, waits for results, and combines them.

All communication goes through the KillerBee website API.
No direct HTTP between bees.

Workflow:
1. Login to KillerBee
2. Poll for assigned work (components from RajaBee or higher GiantQueen)
3. When a component arrives: use local Ollama to split into sub-components
4. Post sub-components to KillerBee
5. Poll until all sub-components have results
6. Use local Ollama to combine results
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


class GiantQueenClient:
    """
    GiantQueen -- Mid-level coordinator.

    Polls KillerBee for assigned components, splits them into
    sub-components for DwarfQueens, waits for results, combines them.
    """

    def __init__(self, server_url: str, swarm_id: int,
                 username: str, password: str,
                 model_name: str = "llama3.2:3b",
                 ollama_url: str = "http://localhost:11434",
                 poll_interval: int = 5):
        self.server_url = server_url
        self.swarm_id = swarm_id
        self.model_name = model_name
        self.poll_interval = poll_interval
        self.member_id = None
        self.subordinate_type = "dwarf_queen"
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
        print_banner("GiantQueen -- Mid-Level Coordinator")
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
                self.swarm_id, "giant_queen", self.model_name
            )
            self.member_id = reg_data.get("member_id", self.kb.user_id)
            print(f"  Registered as GiantQueen (member_id={self.member_id})")
        except Exception as e:
            print(f"  [WARN] Registration: {e}")
            self.member_id = self.kb.user_id

        # ── Buzzing: Discover, Calibrate, Get Fractions ──────────────
        self._buzzing_cycle(self.subordinate_type)
        # ─────────────────────────────────────────────────────────────

        print_banner("GiantQueen is RUNNING. Polling for work...")
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
        """Thorough calibration: 3 big questions, 1s polling, averaged scores."""
        print_banner("BUZZING: Running Calibration Test", char="-")
        NUM_ROUNDS = 3
        CAL_POLL = 1  # 1-second polling during calibration for accuracy

        # Generate 3 different big calibration questions
        cal_questions = []
        for i in range(NUM_ROUNDS):
            print(f"  [BUZZING] Generating calibration question {i+1}/{NUM_ROUNDS}...")
            q = self.ai.ask(
                prompt=("Generate a question that requires a detailed, comprehensive "
                        "answer of at least 4 paragraphs. Pick a rich topic like "
                        "history, science, economics, or geopolitics. "
                        "Just output the question, nothing else."),
                model=self.model_name,
                temperature=0.9
            ).strip()
            cal_questions.append(q)
            print(f"  [BUZZING] Q{i+1}: {q[:120]}...")

        dummy_question = "Name three colors of the rainbow. Reply in three words only."

        # Collect times and answers: sub_id -> {times: [], answers: [], questions: [], name: str}
        all_data = {}
        for sub in self.subordinates:
            sub_id = sub.get("member_id") or sub.get("id")
            sub_name = sub.get("username", f"member-{sub_id}")
            all_data[sub_id] = {"times": [], "answers": [], "questions": [], "name": sub_name}

        # Run each round: for each question, test each worker sequentially
        for round_num, question in enumerate(cal_questions):
            print_banner(f"BUZZING: Round {round_num+1}/{NUM_ROUNDS}", char="-")
            for sub in self.subordinates:
                sub_id = sub.get("member_id") or sub.get("id")
                sub_name = all_data[sub_id]["name"]
                try:
                    # Dummy reset: flush LLM prompt cache
                    print(f"  [BUZZING] R{round_num+1} Resetting cache for {sub_name}...")
                    try:
                        dummy_data = self.kb._request(
                            "POST", f"/api/member/{sub_id}/calibration", {
                                "task": dummy_question,
                                "component_type": "task"
                            }
                        )
                        dummy_comp_id = dummy_data.get("component_id") or dummy_data.get("id")
                        dummy_waited = 0
                        while dummy_waited < 120:
                            time.sleep(CAL_POLL)
                            dummy_waited += CAL_POLL
                            try:
                                dummy_resp = self.kb._request(
                                    "GET", f"/api/component/{dummy_comp_id}/status"
                                )
                                if dummy_resp.get("status") == "completed":
                                    break
                            except:
                                pass
                    except Exception as e:
                        print(f"  [BUZZING] Cache reset failed for {sub_name}: {e}")

                    # Real calibration measurement with 1s polling
                    print(f"  [BUZZING] R{round_num+1} Sending calibration to {sub_name}...")
                    start_time = time.time()
                    cal_data = self.kb._request(
                        "POST", f"/api/member/{sub_id}/calibration", {
                            "task": question,
                            "component_type": "task"
                        }
                    )
                    comp_id = cal_data.get("component_id") or cal_data.get("id")
                    max_wait = 60
                    waited = 0
                    while waited < max_wait:
                        time.sleep(CAL_POLL)
                        waited += CAL_POLL
                        try:
                            comp_resp = self.kb._request(
                                "GET", f"/api/component/{comp_id}/status"
                            )
                            if (comp_resp.get("status") == "completed"
                                    and comp_resp.get("result")):
                                elapsed = time.time() - start_time
                                all_data[sub_id]["times"].append(elapsed)
                                all_data[sub_id]["answers"].append(comp_resp["result"])
                                all_data[sub_id]["questions"].append(question)
                                print(f"  [BUZZING] R{round_num+1} {sub_name} "
                                      f"completed in {elapsed:.1f}s")
                                print(f"  [BUZZING] {sub_name} FULL ANSWER:")
                                print(f"  ---BEGIN---")
                                print(f"  {comp_resp['result'][:500]}...")
                                print(f"  ---END---")
                                break
                        except:
                            pass
                    else:
                        print(f"  [BUZZING] R{round_num+1} {sub_name} timed out")
                except Exception as e:
                    print(f"  [BUZZING] R{round_num+1} Failed for {sub_name}: {e}")

        # Score each subordinate using averaged times and quality
        print_banner("BUZZING: Scoring Subordinates (averaged)", char="-")

        # Calculate average times
        avg_times = {}
        for sub_id, data in all_data.items():
            if data["times"]:
                avg_times[sub_id] = sum(data["times"]) / len(data["times"])
                print(f"  [BUZZING] {data['name']}: times={[round(t,1) for t in data['times']]}, "
                      f"avg={avg_times[sub_id]:.1f}s")

        if not avg_times:
            print("  [BUZZING] No calibration results. Skipping.")
            return

        fastest = min(avg_times.values())

        for sub_id, data in all_data.items():
            if sub_id not in avg_times:
                continue

            # Speed score from averaged time
            speed_score = 10.0 * (fastest / avg_times[sub_id])
            speed_score = round(max(1.0, min(10.0, speed_score)), 1)

            # Quality: judge each answer, average the scores
            q_scores = []
            for answer, question in zip(data["answers"], data["questions"]):
                quality_prompt = (
                    f"Rate the following answer from 1 to 10 for completeness "
                    f"and accuracy. The question was: \"{question}\"\n\n"
                    f"Answer to rate:\n{answer}\n\n"
                    f"Reply with ONLY a single number from 1 to 10, nothing else."
                )
                print(f"  [BUZZING] Judging {data['name']}...")
                quality_text = self.ai.ask(
                    prompt=quality_prompt,
                    model=self.model_name,
                    temperature=0.1
                ).strip()
                print(f"  [BUZZING] JUDGE RAW RESPONSE: \"{quality_text}\"")
                try:
                    qs = float(''.join(c for c in quality_text if c.isdigit() or c == '.'))
                    q_scores.append(max(1.0, min(10.0, qs)))
                except (ValueError, TypeError):
                    q_scores.append(5.0)

            quality_score = round(sum(q_scores) / len(q_scores), 1) if q_scores else 5.0
            buzzing = round(speed_score * quality_score, 1)

            print(f"  [BUZZING] {data['name']}: speed={speed_score}, "
                  f"quality={quality_score} (from {[round(q,1) for q in q_scores]}), "
                  f"buzzing={buzzing}")

            try:
                self.kb.report_buzzing(
                    sub_id, speed_score, quality_score, self.member_id
                )
                print(f"  [BUZZING] Reported buzzing for {data['name']}")
            except Exception as e:
                print(f"  [BUZZING] Failed to report buzzing for "
                      f"{data['name']}: {e}")

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
                print(f"  Total: {sum(f.get('fraction', 0) for f in self.fractions):.3f}")
            else:
                print("  [BUZZING] No fractions received. "
                      "Will use equal splitting.")
        except Exception as e:
            print(f"  [BUZZING] Could not fetch fractions: {e}")

    # ── Main Loop ─────────────────────────────────────────────────────

    def _main_loop(self):
        """Poll KillerBee for assigned components and process them."""
        while True:
            try:
                # Periodically re-discover subordinates
                self._poll_count += 1
                if self._poll_count % self.rediscovery_interval == 0:
                    self._buzzing_cycle(self.subordinate_type)

                # Don't accept work until we have subordinates
                if not self.subordinates:
                    print(f"  Waiting for subordinates to join... "
                          f"(checking every {self.poll_interval}s)", end="\r")
                    self._buzzing_cycle(self.subordinate_type)
                    time.sleep(self.poll_interval)
                    continue

                # First: check for work assigned directly to me
                work = self.kb.get_my_work(self.member_id)
                if work:
                    for component in work:
                        comp_id = component.get("id") or component.get("component_id")
                        task = component.get("task", "")
                        status = component.get("status", "")
                        if status in ("pending", "assigned", ""):
                            original_task = component.get("original_task", task)
                            print(f"\n  [COMPONENT {comp_id}] Assigned to me: "
                                  f"{task[:80]}...")
                            self._process_component(comp_id, task, original_task)
                else:
                    # Second: check for unclaimed components I can claim
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
                                break
                            except Exception as e:
                                print(f"  [COMPONENT {comp_id}] Could not claim: {e}")
                                continue
                    else:
                        print(f"  Polling... no work available. "
                              f"({len(self.subordinates)} subordinates, "
                              f"waiting {self.poll_interval}s)", end="\r")
            except Exception as e:
                print(f"  [ERROR] Polling failed: {e}")

            time.sleep(self.poll_interval)

    def _process_component(self, component_id: int, task: str, original_task: str = ""):
        """Process a component: split into sub-components, wait, combine."""
        start_time = time.time()
        original_task = original_task or task

        # Step 1: Claim the component
        try:
            self.kb.claim_component(component_id, self.member_id)
            print(f"  [COMPONENT {component_id}] Claimed")
        except Exception as e:
            print(f"  [COMPONENT {component_id}] [WARN] Claim: {e}")

        # Step 2: Split into sub-components using local Ollama
        print(f"  [COMPONENT {component_id}] Splitting into sub-components...")
        sub_components = self._split_component(task, original_task)
        print(f"  [COMPONENT {component_id}] Split into "
              f"{len(sub_components)} sub-components")

        for i, sc in enumerate(sub_components):
            print(f"    Sub-component {i+1}: {sc[:70]}...")

        # Step 3: Post sub-components to KillerBee
        children_data = [{"task": sc} for sc in sub_components]
        try:
            split_result = self.kb.split_component(component_id, children_data)
            print(f"  [COMPONENT {component_id}] Sub-components posted")
        except Exception as e:
            print(f"  [COMPONENT {component_id}] [ERROR] "
                  f"Failed to post sub-components: {e}")
            return

        # Step 4: Wait for all sub-components to have results
        print(f"  [COMPONENT {component_id}] Waiting for DwarfQueens...")
        child_results = self._wait_for_children(component_id, split_result)

        if not child_results:
            print(f"  [COMPONENT {component_id}] [ERROR] "
                  f"No child results received")
            return

        # Step 5: Combine results
        print(f"  [COMPONENT {component_id}] Combining "
              f"{len(child_results)} results...")
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

    def _split_component(self, task: str, original_task: str = "") -> list:
        """Use local Ollama to split a component into sub-components.

        If fractions are available from Buzzing calibration, the number of
        sub-components matches the number of subordinates (DwarfQueens),
        and each is sized proportionally by fraction.
        """
        original_task = original_task or task
        num_subs = len(self.fractions) if self.fractions else None

        if num_subs and num_subs >= 2:
            fraction_lines = []
            for i, f in enumerate(self.fractions):
                name = f.get("username", f.get("name", f"Subordinate {i+1}"))
                frac = f.get("fraction", round(1.0 / num_subs, 2))
                fraction_lines.append(
                    f"Sub-component {i+1} should cover about {frac:.2f} "
                    f"of the total work (for {name})"
                )
            fraction_instructions = "\n".join(fraction_lines)

            prompt = f"""Split this into exactly {num_subs} parts.

Original question: "{original_task}"
Component to split: {task}

Size proportionally:
{fraction_instructions}"""
        else:
            prompt = f"""Split this into 2-3 parts.

Original question: "{original_task}"
Component to split: {task}"""

        raw = self.ai.ask(
            prompt=prompt,
            model=self.model_name,
            temperature=0.3
        )

        from smart_splitter import smart_split
        result = smart_split(raw)

        max_expected = num_subs if num_subs else 3
        if len(result) < 2:
            result = [task]
        elif len(result) > max_expected * 2:
            print(f"  [WARNING] Split returned {len(result)} items "
                  f"(expected {max_expected}). Falling back to single component.")
            result = [task]

        return result

    def _wait_for_children(self, component_id: int,
                           split_result: dict) -> list:
        """Poll until all children of this component have results."""
        child_ids = split_result.get("child_ids",
                                     split_result.get("component_ids", []))
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
                          f"{len(completed_results)} children completed "
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
        """Use local Ollama to combine child results."""
        formatted = ""
        for i, cr in enumerate(child_results):
            task_desc = cr.get("task", f"Sub-component {i+1}")
            result_text = cr.get("result", "[No result]")
            formatted += f"\n{'='*40}\n"
            formatted += f"SECTION {i+1}: {task_desc[:60]}\n"
            formatted += f"{'='*40}\n"
            formatted += f"{result_text}\n"

        prompt = f"""Combine these {len(child_results)} results into one answer.

Original question: {original_task}
This component: {component_task}

Results:
{formatted}

Combine into one coherent answer. Remove redundancy, keep all important details."""

        return self.ai.ask(
            prompt=prompt,
            model=self.model_name,
            temperature=0.5
        )


def main():
    parser = argparse.ArgumentParser(
        description="GiantQueen -- Mid-level coordinator. "
                    "Connects to KillerBee website API."
    )
    parser.add_argument('--server', type=str,
                        default=os.environ.get('KILLERBEE_URL'),
                        help='KillerBee server URL (env: KILLERBEE_URL)')
    parser.add_argument('--swarm-id', type=int,
                        default=int(os.environ.get('KILLERBEE_SWARM_ID', '1')),
                        help='Swarm ID (env: KILLERBEE_SWARM_ID, default 1)')
    parser.add_argument('--username', type=str,
                        default=os.environ.get('KILLERBEE_USERNAME'),
                        help='Username (env: KILLERBEE_USERNAME)')
    parser.add_argument('--password', type=str,
                        default=os.environ.get('KILLERBEE_PASSWORD'),
                        help='Password (env: KILLERBEE_PASSWORD)')
    parser.add_argument('--model', type=str,
                        default=os.environ.get('KILLERBEE_MODEL', 'qwen3:8b'),
                        help='Ollama model (env: KILLERBEE_MODEL, tier default qwen3:8b)')
    parser.add_argument('--ollama-url', type=str,
                        default=os.environ.get('OLLAMA_URL', 'http://localhost:11434'),
                        help='Ollama API URL (env: OLLAMA_URL)')
    parser.add_argument('--poll-interval', type=int, default=5,
                        help='Seconds between polls (default: 5)')
    args = parser.parse_args()

    missing = [k for k in ('server', 'username', 'password') if getattr(args, k) is None]
    if missing:
        parser.error("Missing " + ", ".join('--' + m for m in missing)
                     + " (or env KILLERBEE_URL / KILLERBEE_USERNAME / KILLERBEE_PASSWORD)")

    queen = GiantQueenClient(
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
