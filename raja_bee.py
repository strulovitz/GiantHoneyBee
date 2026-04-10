"""
RajaBee — The King of the Bees
===============================
Named after Megachile pluto (Wallace's Giant Bee), the largest bee in the world.
Raja Ofu = "king of the bees" in Indonesian.

The RajaBee coordinates multiple GiantQueens (named after Apis dorsata, the Giant
Honey Bee). Each GiantQueen is a mid-level coordinator that delegates to DwarfQueens
(named after Apis florea, the Red Dwarf Honey Bee), who have the actual Workers.

Hierarchy: Worker Bee → DwarfQueen → GiantQueen → RajaBee
"""

import sys
import os
import time
import json
import requests
import concurrent.futures

# Add HoneycombOfAI to path for AI backend
HONEYCOMB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'HoneycombOfAI')
sys.path.insert(0, HONEYCOMB_PATH)

from ollama_client import OllamaClient

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    console = Console()
    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    class FakeConsole:
        def print(self, *args, **kwargs):
            text = str(args[0]) if args else ""
            # Strip rich markup for plain output
            import re
            clean = re.sub(r'\[.*?\]', '', text)
            print(clean)
    console = FakeConsole()


class RajaBee:
    """
    The Raja Bee — King of the Bees.

    She coordinates multiple GiantQueens, each managing their own sub-hierarchy
    of DwarfQueens and Workers.
    She is responsible for:
    1. Querying GiantQueens for their capabilities (Report Up pattern)
    2. Splitting a complex task into major components proportionally
    3. Delegating each component to a GiantQueen (in parallel)
    4. Combining all GiantQueens' results into one mega-answer (Royal Honey)
    """

    def __init__(self, model_name: str = "llama3.2:3b",
                 ollama_url: str = "http://localhost:11434",
                 giant_queen_endpoints: list = None,
                 timeout: int = 600):
        self.model_name = model_name
        self.giant_queen_endpoints = giant_queen_endpoints or []
        self.timeout = timeout
        self.ai = OllamaClient(base_url=ollama_url)
        self.giant_queen_capabilities = {}

    def start(self):
        """Start the RajaBee and verify connections."""
        if HAS_RICH:
            console.print(Panel(
                f"[bold red]👑👑 Raja Bee started! 👑👑[/]\n"
                f"Model: {self.model_name}\n"
                f"GiantQueens: {len(self.giant_queen_endpoints)}",
                title="Raja Bee — King of the Bees",
                border_style="red"
            ))
        else:
            console.print(f"Raja Bee started! Model: {self.model_name}, GiantQueens: {len(self.giant_queen_endpoints)}")

        if not self.ai.is_available():
            console.print(f"  Cannot connect to Ollama! Is it running?")
            return False
        console.print(f"  Connected to {self.ai.backend_name()}")

        # Query all GiantQueens for capabilities
        self._discover_giant_queens()

        return len(self.giant_queen_capabilities) > 0

    def _discover_giant_queens(self):
        """Query each GiantQueen for her capabilities (Report Up pattern)."""
        console.print(f"\n  Discovering GiantQueens...")
        self.giant_queen_capabilities = {}

        for endpoint in self.giant_queen_endpoints:
            try:
                resp = requests.get(f"{endpoint}/capabilities", timeout=10)
                if resp.status_code == 200:
                    caps = resp.json()
                    self.giant_queen_capabilities[endpoint] = caps
                    console.print(
                        f"  Found GiantQueen at {endpoint}: "
                        f"{caps.get('total_workers', '?')} workers, "
                        f"model: {caps.get('model', '?')}"
                    )
                else:
                    console.print(f"  GiantQueen at {endpoint} responded with status {resp.status_code}")
            except Exception as e:
                console.print(f"  Cannot reach GiantQueen at {endpoint}: {e}")

        if not self.giant_queen_capabilities:
            console.print(f"  No GiantQueens available!")
        else:
            total_workers = sum(c.get('total_workers', 1) for c in self.giant_queen_capabilities.values())
            console.print(f"  Total: {len(self.giant_queen_capabilities)} GiantQueens, {total_workers} Workers across all hives")

    def _calculate_proportions(self):
        """Calculate work proportions based on GiantQueen capabilities."""
        total_workers = sum(
            c.get('total_workers', 1) for c in self.giant_queen_capabilities.values()
        )
        proportions = {}
        for endpoint, caps in self.giant_queen_capabilities.items():
            workers = caps.get('total_workers', 1)
            proportions[endpoint] = workers / total_workers if total_workers > 0 else 1.0 / len(self.giant_queen_capabilities)
        return proportions

    def split_task(self, task: str) -> list:
        """
        Split a complex task into major components — one per GiantQueen.

        Unlike a DwarfQueen's split (which creates small subtasks), the RajaBee
        splits into MAJOR independent components, each substantial enough
        for an entire sub-hierarchy to work on.
        """
        num_giant_queens = len(self.giant_queen_capabilities)
        proportions = self._calculate_proportions()

        # Build proportion hints for the prompt
        proportion_hints = ""
        for i, (endpoint, prop) in enumerate(proportions.items()):
            caps = self.giant_queen_capabilities[endpoint]
            workers = caps.get('total_workers', 1)
            proportion_hints += f"\n- Component {i+1}: should be ~{prop*100:.0f}% of the total work ({workers} workers available)"

        console.print(f"\n  Splitting task into {num_giant_queens} major components...")

        prompt = f"""You are a SENIOR coordinator managing {num_giant_queens} independent teams. Your job is to split one complex task into exactly {num_giant_queens} MAJOR independent components.

IMPORTANT RULES:
- Each component must be INDEPENDENT — it can be completed without knowing the results of other components
- Each component should be a SUBSTANTIAL piece of work requiring research and synthesis — NOT a simple single question
- Components should be PROPORTIONAL to the available resources:
{proportion_hints}
- A team with more resources should get a bigger/more complex component
- Together, all components should fully cover the original task

The complex task is: {task}

Return ONLY a JSON array of {num_giant_queens} strings, each describing one major component. Example format:
["first major component description", "second major component description"]

Your JSON array:"""

        components = self.ai.ask_for_json_list(
            prompt=prompt,
            model=self.model_name,
            temperature=0.3
        )

        # Ensure correct count
        if len(components) < num_giant_queens:
            for i in range(len(components), num_giant_queens):
                components.append(f"Provide additional analysis about: {task} (aspect {i+1})")
        elif len(components) > num_giant_queens:
            components = components[:num_giant_queens]

        # Display components
        if HAS_RICH:
            table = Table(title="Major Components for GiantQueens", border_style="red")
            table.add_column("#", style="bold")
            table.add_column("GiantQueen", style="cyan")
            table.add_column("Component", style="italic")
            table.add_column("Workers", style="green")
            for i, (endpoint, component) in enumerate(zip(self.giant_queen_capabilities.keys(), components)):
                caps = self.giant_queen_capabilities[endpoint]
                table.add_row(
                    str(i + 1),
                    endpoint.split(":")[-1],
                    component[:80] + ("..." if len(component) > 80 else ""),
                    str(caps.get('total_workers', '?'))
                )
            console.print(table)

        return components

    def delegate_to_giant_queens(self, components: list) -> list:
        """
        Send each component to a different GiantQueen IN PARALLEL.
        Each GiantQueen processes it through her own sub-hierarchy (delegating
        to DwarfQueens, who distribute to Workers, combining results).
        """
        endpoints = list(self.giant_queen_capabilities.keys())
        results = []
        start_time = time.time()

        console.print(f"\n  Delegating {len(components)} components to {len(endpoints)} GiantQueens in parallel...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(endpoints)) as executor:
            future_to_giant_queen = {}
            for i, component in enumerate(components):
                endpoint = endpoints[i]
                future = executor.submit(self._send_to_giant_queen, endpoint, component)
                future_to_giant_queen[future] = endpoint

            for future in concurrent.futures.as_completed(future_to_giant_queen):
                endpoint = future_to_giant_queen[future]
                try:
                    result = future.result()
                    results.append({
                        "giant_queen": endpoint,
                        "component": components[endpoints.index(endpoint)],
                        "result": result["result"],
                        "time": result.get("time", 0)
                    })
                    console.print(f"  GiantQueen {endpoint} completed in {result.get('time', '?')}s")
                except Exception as e:
                    results.append({
                        "giant_queen": endpoint,
                        "component": components[endpoints.index(endpoint)],
                        "result": f"[ERROR] {str(e)}",
                        "time": 0
                    })
                    console.print(f"  GiantQueen {endpoint} FAILED: {e}")

        elapsed = time.time() - start_time
        console.print(f"  All {len(endpoints)} GiantQueens completed in {elapsed:.1f}s total")

        return results

    def _send_to_giant_queen(self, endpoint: str, task: str) -> dict:
        """Send a task to a GiantQueen via HTTP and wait for the result."""
        resp = requests.post(
            f"{endpoint}/process",
            json={"task": task},
            timeout=self.timeout
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            raise Exception(f"HTTP {resp.status_code}: {resp.text}")

    def combine_results(self, original_task: str, giant_queen_results: list) -> str:
        """
        Combine all GiantQueens' results into one Royal Honey.

        Unlike a DwarfQueen's combine (which merges subtask outputs), the RajaBee
        combines COMPLETE, SYNTHESIZED sections from expert teams.
        """
        console.print(f"\n  Combining results from {len(giant_queen_results)} GiantQueens into Royal Honey...")

        formatted = ""
        for i, qr in enumerate(giant_queen_results):
            formatted += f"\n{'='*40}\n"
            formatted += f"SECTION {i+1} (from team handling: {qr['component'][:60]})\n"
            formatted += f"{'='*40}\n"
            formatted += f"{qr['result']}\n"

        prompt = f"""You are a SENIOR editor combining results from {len(giant_queen_results)} expert teams into one comprehensive final document.

The original task was: {original_task}

Here are the completed sections from each team:
{formatted}

Please combine ALL sections into ONE well-organized, coherent final document.
- Each section was completed by a separate team working independently
- Integrate the sections smoothly — do NOT just concatenate them
- Remove any redundancy between sections
- Organize with clear headings and logical flow
- Keep ALL important details from every team's contribution
- The final document should read as if one expert wrote the entire thing

Your combined final document:"""

        royal_honey = self.ai.ask(
            prompt=prompt,
            model=self.model_name,
            temperature=0.5
        )

        return royal_honey

    def process_royal_nectar(self, task: str) -> str:
        """
        The complete RajaBee pipeline: receive task, produce Royal Honey.

        1. Split task into major components (proportional to GiantQueen capabilities)
        2. Delegate components to GiantQueens in parallel
        3. Combine GiantQueens' results into Royal Honey
        """
        if HAS_RICH:
            console.print(Panel(
                f"[bold red]Royal Nectar received![/]\n\n[italic]{task}[/]",
                title="👑👑 Incoming Royal Nectar",
                border_style="red"
            ))
        else:
            console.print(f"\nRoyal Nectar received: {task}")

        total_start = time.time()

        # Step 1: Split into major components
        components = self.split_task(task)

        # Step 2: Delegate to GiantQueens in parallel
        giant_queen_results = self.delegate_to_giant_queens(components)

        # Step 3: Combine into Royal Honey
        royal_honey = self.combine_results(task, giant_queen_results)

        total_elapsed = time.time() - total_start

        if HAS_RICH:
            console.print(Panel(
                f"[bold yellow]Royal Honey is ready![/]\n"
                f"Total time: {total_elapsed:.1f} seconds\n"
                f"GiantQueens used: {len(self.giant_queen_capabilities)}\n"
                f"Total workers across all hives: {sum(c.get('total_workers', 1) for c in self.giant_queen_capabilities.values())}",
                title="👑👑 Royal Honey Delivered",
                border_style="yellow"
            ))
        else:
            console.print(f"\nRoyal Honey ready! Time: {total_elapsed:.1f}s, GiantQueens: {len(self.giant_queen_capabilities)}")

        return royal_honey

    def process_nectar(self, task: str) -> str:
        """
        Alias for process_royal_nectar — makes RajaBee wrappable in
        queen_http_wrapper.py for N-level hierarchies.
        """
        return self.process_royal_nectar(task)
