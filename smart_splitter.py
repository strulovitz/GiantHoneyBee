"""
Smart text splitter — detects how the LLM chose to separate items
and extracts them. No format forced on the LLM.

Algorithm:
1. Look for any non-alphanumeric pattern that repeats at the start of lines
2. If found, split by that pattern
3. If not found, fall back to known formats (numbered, bullets, headers, JSON, table)
4. If nothing works, return the whole text as one item
"""

import re
import json
from collections import Counter


def smart_split(text: str) -> list:
    """Split LLM output into parts, detecting whatever format it used."""
    text = text.strip()
    if not text:
        return []

    # Step 1: Try to detect a repeating pattern at the start of lines
    lines = text.split("\n")
    lines = [line for line in lines if line.strip()]  # remove empty lines

    if len(lines) >= 2:
        result = _detect_repeating_prefix(lines)
        if result and len(result) >= 2:
            return result

    # Step 2: Fall back to known formats

    # Try JSON array
    result = _try_json(text)
    if result and len(result) >= 2:
        return result

    # Try markdown table
    result = _try_table(lines)
    if result and len(result) >= 2:
        return result

    # Try paragraph splitting (double newlines)
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    if len(paragraphs) >= 2:
        return paragraphs

    # Step 3: Nothing worked — return whole text as one item
    return [text]


def _detect_repeating_prefix(lines: list) -> list:
    """Find any non-alphanumeric pattern that repeats at the start of lines."""

    # Extract the prefix of each line: everything before the first alphanumeric
    # content word starts. A "prefix" is the leading non-content characters.
    prefixes = []
    for line in lines:
        if not line.strip():
            continue
        # Pass the ORIGINAL line (with indentation) so we can detect
        # indented sub-items vs top-level items
        prefix = _extract_line_prefix(line)
        prefixes.append((prefix, line))

    if len(prefixes) < 2:
        return None

    # Group lines by their prefix PATTERN (not exact match, but structure)
    # "1." and "2." have the same pattern: digit + dot
    # "- " and "- " are identical
    # "## " and "## " are identical
    patterns = []
    for prefix, line in prefixes:
        pattern = _prefix_to_pattern(prefix)
        patterns.append((pattern, prefix, line))

    # Count how many times each pattern appears
    pattern_counts = Counter(p[0] for p in patterns)

    # Find the best pattern: must appear 2+ times.
    # Prefer non-indented (top-level) patterns over indented ones.
    # Among same indentation level, prefer most common.
    candidates = [(p, c) for p, c in pattern_counts.items() if c >= 2 and p]
    if not candidates:
        return None

    # Sort: non-indented first, then by count descending
    def sort_key(pc):
        p, c = pc
        is_indented = 1 if p.startswith("I") else 0
        return (is_indented, -c)

    candidates.sort(key=sort_key)
    best_pattern = candidates[0][0]
    best_count = candidates[0][1]

    if not best_pattern or best_count < 2:
        return None

    # Extract items: group lines by the detected pattern
    # Lines matching the pattern start a new item
    # Lines NOT matching get appended to the current item
    items = []
    current_item_lines = []

    for pattern, prefix, line in patterns:
        if pattern == best_pattern:
            # This line starts a new item
            if current_item_lines:
                items.append("\n".join(current_item_lines))
            # Remove the prefix/marker from the line to get clean content
            content = _remove_prefix(line, prefix)
            current_item_lines = [content]
        else:
            # This is a continuation or sub-item — append to current
            if current_item_lines:
                current_item_lines.append(line.strip())
            else:
                # Orphan line before first item — skip or start new item
                current_item_lines = [line.strip()]

    if current_item_lines:
        items.append("\n".join(current_item_lines))

    # Filter out empty items
    items = [item.strip() for item in items if item.strip()]

    return items if len(items) >= 2 else None


def _extract_line_prefix(line: str) -> str:
    """Extract the leading marker/prefix from a line.

    Rule: a-z, A-Z, 0-9 are content. Everything else is a potential marker.
    The prefix is everything at the start of the line before the actual
    content begins, including digit+punctuation markers like "1." or "A)".

    Examples:
        "1. Research cats" -> "1. "
        "- Research cats" -> "- "
        "## Section one" -> "## "
        "* Item" -> "* "
        "A) First" -> "A) "
        "🔬 Research" -> "🔬 "
        "→ Item" -> "→ "
        "Research cats" -> ""
    """
    # First try: digit or letter followed by punctuation (1. 2. A) B. etc)
    match = re.match(r'^(\s*(?:[\d]+[.\)]\s+|[a-zA-Z][.\)]\s+))', line)
    if match:
        return match.group(1)

    # Second try: any sequence of non-alphanumeric characters at the start
    # (this catches -, *, #, ##, →, emoji, etc)
    # Use [^a-zA-Z0-9] to match anything that's not a letter or digit
    match = re.match(r'^(\s*[^a-zA-Z0-9\s]+\s*)', line)
    if match:
        return match.group(1)

    # Also catch markdown headers (## with space)
    match = re.match(r'^(\s*#{1,6}\s+)', line)
    if match:
        return match.group(1)

    return ""


def _prefix_to_pattern(prefix: str) -> str:
    """Convert a specific prefix to a generalized pattern.

    "1. " and "2. " both become "D. " (D = any digit sequence)
    "A) " and "B) " both become "L) " (L = any single letter)
    "- " stays "- "
    "## " stays "## "
    "🔬 " and "🏥 " both become "E " (E = any emoji/non-ascii)

    Also encodes indentation level so sub-items don't match top-level.
    """
    if not prefix:
        return ""

    # Measure indentation (spaces/tabs at start)
    indent = len(prefix) - len(prefix.lstrip())
    indent_tag = f"I{indent}_" if indent > 0 else ""

    stripped = prefix.strip()

    # Replace single letter markers with L FIRST (before digit replacement)
    pattern = re.sub(r'^[a-zA-Z]([.\)])', r'L\1', stripped)
    # Then replace digit sequences with D
    pattern = re.sub(r'\d+', 'D', pattern)
    # Replace non-ASCII characters (emoji, unicode symbols) with E
    pattern = re.sub(r'[^\x00-\x7F]+', 'E', pattern)

    return indent_tag + pattern


def _remove_prefix(line: str, prefix: str) -> str:
    """Remove the detected prefix from a line to get clean content."""
    if prefix and line.strip().startswith(prefix.strip()):
        return line.strip()[len(prefix.strip()):].strip()
    # Try removing by pattern
    stripped = line.strip()
    match = re.match(r'^(?:[\d]+[.\)]\s*|[a-zA-Z][.\)]\s*|[^\w\s]+\s*|#{1,6}\s+)', stripped)
    if match:
        return stripped[match.end():].strip()
    return stripped


def _try_json(text: str) -> list:
    """Try to parse as JSON array."""
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [str(item) for item in result if str(item).strip()]
    except json.JSONDecodeError:
        pass

    # Try to find the outermost JSON array (greedy match)
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return [str(item) for item in result if str(item).strip()]
        except json.JSONDecodeError:
            pass

    return None


def _try_table(lines: list) -> list:
    """Try to parse as markdown table."""
    # A markdown table has | characters and a separator line with ---
    has_pipes = sum(1 for line in lines if '|' in line)
    has_separator = any(re.match(r'^[\s|:-]+$', line) for line in lines)

    if has_pipes >= 3 and has_separator:
        rows = []
        for line in lines:
            if '|' in line and not re.match(r'^[\s|:-]+$', line):
                cells = [cell.strip() for cell in line.split('|') if cell.strip()]
                if cells:
                    rows.append(" | ".join(cells))
        # Skip header row
        if len(rows) > 1:
            return rows[1:]  # skip header
        return rows

    return None


# ============================================================
# TESTS
# ============================================================

if __name__ == "__main__":
    tests = {
        "Numbered list (1. 2. 3.)": """1. Research light sail propulsion including how solar photons provide thrust, current projects like Breakthrough Starshot, and the pros and cons of this approach for reaching Alpha Centauri.
2. Research nuclear pulse propulsion including Project Orion, how nuclear explosions generate thrust, and the pros and cons for interstellar distances.
3. Research fusion propulsion including how fusion reactions could power spacecraft, current research status, and pros and cons compared to other methods.
4. Research generation ships and hibernation concepts including how humans could survive multi-decade journeys, life support challenges, and pros and cons.""",

        "Bullet points (-)": """- Light sail propulsion: how solar photons provide thrust, Breakthrough Starshot, pros and cons
- Nuclear pulse propulsion: Project Orion, nuclear explosions for thrust, pros and cons
- Fusion propulsion: fusion reactions for power, current research, pros and cons
- Generation ships and hibernation: surviving long journeys, life support, pros and cons""",

        "Markdown headers (##)": """## Light Sail Propulsion
Research how solar photons provide thrust, current projects like Breakthrough Starshot, and evaluate pros and cons.

## Nuclear Pulse Propulsion
Research Project Orion, how nuclear explosions generate thrust, and evaluate pros and cons.

## Fusion Propulsion
Research how fusion reactions could power spacecraft, current status, and compare to other methods.""",

        "Letter markers (A. B. C.)": """A. Investigate propulsion methods for interstellar travel including light sails, nuclear pulse, and fusion drives
B. Investigate life support systems for multi-decade space journeys including hibernation and generation ships
C. Investigate navigation and communication challenges across interstellar distances""",

        "Star bullets (*)": """* Propulsion technologies: light sails, nuclear pulse, fusion, antimatter
* Life support: hibernation, generation ships, closed-loop systems
* Navigation and communication across light-year distances
* Radiation protection for crew and electronics""",

        "Emoji bullets": """🔬 Research propulsion methods including light sails, nuclear pulse, and fusion drives
🏥 Research life support systems for multi-decade journeys
📡 Research navigation and communication across interstellar distances
🛡️ Research radiation protection for crew and electronics""",

        "Arrow bullets (→)": """→ Propulsion methods for reaching Alpha Centauri
→ Life support systems for decades-long journeys
→ Navigation and communication across light-years""",

        "Hierarchical (top-level with sub-items)": """1. Propulsion Methods
   - Light sails using solar photons
   - Nuclear pulse propulsion
   - Fusion drives
2. Life Support Systems
   - Hibernation technology
   - Generation ships
   - Closed-loop recycling
3. Navigation and Communication
   - Gravitational slingshots
   - Quantum communication""",

        "JSON array": """["Research propulsion methods including light sails and nuclear pulse", "Research life support systems for long journeys", "Research navigation and communication across stellar distances"]""",

        "Plain paragraphs (no markers)": """Research all propulsion methods that could reach Alpha Centauri including light sails, nuclear pulse propulsion, fusion drives, and antimatter engines. Evaluate the pros and cons of each.

Research life support systems needed for multi-decade space journeys including hibernation, generation ships, and closed-loop life support. Evaluate feasibility and challenges.

Research navigation and communication challenges for interstellar travel including gravitational slingshots, laser communication, and quantum entanglement.""",

        "Nested JSON (the bug we had)": """{"propulsion": {"light_sails": {"description": "Use photons", "pros": ["Low mass"], "cons": ["Slow"]}, "nuclear": {"description": "Use explosions", "pros": ["Fast"], "cons": ["Radiation"]}}}""",
    }

    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    for name, text in tests.items():
        result = smart_split(text)
        print(f"{'='*60}")
        print(f"TEST: {name}")
        print(f"Result: {len(result)} items")
        for i, item in enumerate(result):
            preview = item[:80].replace('\n', ' | ')
            print(f"  [{i+1}] {preview}{'...' if len(item) > 80 else ''}")
        print()
