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

        print_banner("GiantQueen is RUNNING. Polling for work...")
        self._main_loop()
        return True

    def _main_loop(self):
        """Poll KillerBee for assigned components and process them."""
        while True:
            try:
                work = self.kb.get_my_work(self.member_id)
                if work:
                    for component in work:
                        comp_id = component.get("id") or component.get("component_id")
                        task = component.get("task", "")
                        status = component.get("status", "")
                        if status in ("pending", "assigned", ""):
                            original_task = component.get("original_task", task)
                            print(f"\n  [COMPONENT {comp_id}] Received: "
                                  f"{task[:80]}...")
                            self._process_component(comp_id, task, original_task)
                else:
                    print(f"  Polling... no assigned work. "
                          f"(waiting {self.poll_interval}s)", end="\r")
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
        """Use local Ollama to split a component into sub-components."""
        original_task = original_task or task
        prompt = f"""You are a coordinator splitting a task into 2-3 independent sub-components for separate teams.

CRITICAL CONTEXT: The ORIGINAL QUESTION that started this whole process was:
"{original_task}"

Your specific component to split is: {task}

RULES:
- Each sub-component must be INDEPENDENT
- Each should be substantial enough for a team to work on
- Together they must fully cover YOUR component
- Every sub-component MUST stay relevant to the ORIGINAL QUESTION above
- Do NOT drift into unrelated topics — always tie back to what was originally asked

Return ONLY a JSON array of strings. Example: ["sub-component 1", "sub-component 2"]

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

        prompt = f"""You are an editor combining results from {len(child_results)} teams into one coherent document.

ORIGINAL QUESTION (what the user actually asked): {original_task}

YOUR SPECIFIC COMPONENT was: {component_task}

Here are the sections from your teams:
{formatted}

Combine into ONE well-organized document that answers YOUR COMPONENT in the context of the ORIGINAL QUESTION.
Stay focused on what was actually asked. Integrate smoothly, remove redundancy, keep all important details.

Your combined document:"""

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
    parser.add_argument('--server', type=str, required=True,
                        help='KillerBee server URL')
    parser.add_argument('--swarm-id', type=int, required=True,
                        help='Swarm ID to join')
    parser.add_argument('--username', type=str, required=True,
                        help='Username for KillerBee login')
    parser.add_argument('--password', type=str, required=True,
                        help='Password for KillerBee login')
    parser.add_argument('--model', type=str, default='llama3.2:3b',
                        help='Ollama model name (default: llama3.2:3b)')
    parser.add_argument('--ollama-url', type=str,
                        default='http://localhost:11434',
                        help='Ollama API URL')
    parser.add_argument('--poll-interval', type=int, default=5,
                        help='Seconds between polls (default: 5)')
    args = parser.parse_args()

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
