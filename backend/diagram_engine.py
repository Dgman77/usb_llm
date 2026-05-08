"""
diagram_engine.py — Mermaid diagram post-processor, validator & auto-repair

Fixes common LLM output issues so diagrams render cleanly in the browser.
No external dependencies — pure Python regex + string ops.
"""

import re


# ═══════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════

def process_diagram(raw: str, diagram_type: str = "flowchart TD") -> str:
    """
    Main entry: extract → fix → validate → wrap.
    Returns a clean ```mermaid ... ``` block ready for the frontend.
    """
    code = _extract_body(raw)
    code = _ensure_header(code, diagram_type)
    code = _fix_syntax(code, diagram_type)
    code = _fix_truncation(code)
    code = _deduplicate_edges(code)
    code = _clean_whitespace(code)
    return f"```mermaid\n{code}\n```"


def is_valid(text: str) -> bool:
    """Check if text looks like a renderable Mermaid diagram."""
    lower = text.lower().strip()
    has_type = any(lower.startswith(t) or f"\n{t}" in lower for t in _HEADERS)
    has_content = len(text.strip().splitlines()) >= 3
    return has_type and has_content


def complexity_score(text: str) -> int:
    """Estimate diagram complexity: count of nodes + edges."""
    nodes = len(re.findall(r'[A-Za-z_]\w*\s*[\[\({]', text))
    edges = len(re.findall(r'--[->]|==>|-.->|\.\.->', text))
    return nodes + edges


# ═══════════════════════════════════════════════════════════
#  INTERNALS
# ═══════════════════════════════════════════════════════════

_HEADERS = [
    "flowchart", "graph ", "sequencediagram", "erdiagram",
    "classdiagram", "statediagram", "gantt", "pie", "mindmap",
]

_DIAGRAM_TYPES_CANONICAL = {
    "flowchart": "flowchart TD",
    "graph": "graph TD",
    "sequencediagram": "sequenceDiagram",
    "erdiagram": "erDiagram",
    "classdiagram": "classDiagram",
    "statediagram": "stateDiagram-v2",
    "statediagram-v2": "stateDiagram-v2",
    "gantt": "gantt",
    "pie": "pie",
    "mindmap": "mindmap",
}


def _extract_body(raw: str) -> str:
    """Pull diagram code out of fences / surrounding text."""
    # ```mermaid ... ```
    m = re.search(r"```mermaid\s*\n?([\s\S]*?)```", raw, re.I)
    if m:
        return m.group(1).strip()

    # ``` <type> ... ```
    m = re.search(
        r"```\s*(flowchart|graph|sequenceDiagram|erDiagram|classDiagram|"
        r"stateDiagram(?:-v2)?|gantt|pie|mindmap)([\s\S]*?)```",
        raw, re.I,
    )
    if m:
        return (m.group(1) + m.group(2)).strip()

    # No fences — look for a line starting with a diagram keyword
    for line_no, line in enumerate(raw.splitlines()):
        ll = line.strip().lower()
        if any(ll.startswith(h) for h in _HEADERS):
            return "\n".join(raw.splitlines()[line_no:]).strip()

    return raw.strip()


def _ensure_header(code: str, diagram_type: str) -> str:
    """Make sure the code starts with a valid Mermaid type header."""
    first = code.split("\n", 1)[0].strip().lower()
    if any(first.startswith(h) for h in _HEADERS):
        return code
    return diagram_type + "\n" + code


def _fix_syntax(code: str, diagram_type: str) -> str:
    """Fix the most common LLM-generated Mermaid errors."""
    lines = code.splitlines()
    fixed = []

    dt_lower = diagram_type.lower()
    is_flowchart = "flowchart" in dt_lower or "graph" in dt_lower
    is_sequence = "sequence" in dt_lower
    is_er = "erdiagram" in dt_lower
    is_class = "classdiagram" in dt_lower
    is_state = "statediagram" in dt_lower
    is_mindmap = "mindmap" in dt_lower

    for i, raw_line in enumerate(lines):
        line = raw_line.rstrip()

        # Skip empty lines early
        if not line.strip():
            fixed.append(line)
            continue

        # ── Flowchart fixes ───────────────────────────
        if is_flowchart:
            # Fix: A -> B  →  A --> B  (single arrow not valid)
            line = re.sub(r'(\w)\s*->\s*(\w)', r'\1 --> \2', line)
            # Fix: unbalanced square brackets in node labels
            line = _balance_brackets(line, "[", "]")
            # Fix: unbalanced curly braces (decision diamonds)
            line = _balance_brackets(line, "{", "}")
            # Fix: unbalanced parens (rounded nodes)
            line = _balance_brackets(line, "(", ")")
            # Fix: pipes in labels break rendering — replace with dashes
            if "[" in line and "]" in line:
                # Only fix pipes INSIDE brackets
                line = re.sub(
                    r'\[([^\]]*)\]',
                    lambda m: "[" + m.group(1).replace("|", " - ") + "]",
                    line,
                )
            # Fix: semicolons at end of lines (not needed, sometimes break)
            line = line.rstrip(";")
            # Fix: quotes inside node labels
            line = re.sub(r'\["([^"]*)"', lambda m: '["' + m.group(1).replace('"', "'") + '"', line)

        # ── Sequence diagram fixes ────────────────────
        if is_sequence:
            # Fix: spaces in actor names — wrap in quotes or remove
            # "My Server" -> MyServer
            line = re.sub(
                r'^(\s*)(participant\s+)(.+?)(\s+as\s+.+)?$',
                lambda m: m.group(1) + m.group(2) + m.group(3).replace(" ", "_") + (m.group(4) or ""),
                line, flags=re.I,
            )
            # Fix: wrong arrow syntax  -> should be ->> or -->>
            line = re.sub(r'(\w)\s*->\s*(\w)', r'\1->>\2', line)

        # ── ER diagram fixes ──────────────────────────
        if is_er:
            # Fix: missing relationship labels
            line = re.sub(r'(\w+)\s*\|\|--o\{\s*(\w+)\s*$', r'\1 ||--o{ \2 : has', line)
            line = re.sub(r'(\w+)\s*\}o--\|\|\s*(\w+)\s*$', r'\1 }o--|| \2 : belongs_to', line)

        # ── State diagram fixes ───────────────────────
        if is_state:
            # Fix: wrong arrow  ->  should be  -->
            line = re.sub(r'(\w)\s*->\s*(\w)', r'\1 --> \2', line)
            # Fix: [*] spacing
            line = re.sub(r'\[\s*\*\s*\]', '[*]', line)

        # ── Universal fixes ───────────────────────────
        # Fix: HTML entities that sneak in
        line = line.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
        # Fix: smart quotes
        line = line.replace("\u201c", '"').replace("\u201d", '"')
        line = line.replace("\u2018", "'").replace("\u2019", "'")
        # Fix: em-dash / en-dash in arrows
        line = line.replace("\u2014", "--").replace("\u2013", "--")

        fixed.append(line)

    return "\n".join(fixed)


def _fix_truncation(code: str) -> str:
    """Handle LLM output that got cut off mid-diagram."""
    lines = code.splitlines()
    if not lines:
        return code

    # Remove incomplete last line (no closing bracket, arrow dangling)
    last = lines[-1].strip()
    if last and not _line_looks_complete(last):
        lines = lines[:-1]

    # Close any unclosed subgraphs
    open_subgraphs = 0
    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("subgraph"):
            open_subgraphs += 1
        elif stripped == "end":
            open_subgraphs = max(0, open_subgraphs - 1)

    for _ in range(open_subgraphs):
        lines.append("    end")

    return "\n".join(lines)


def _line_looks_complete(line: str) -> bool:
    """Check if a line of Mermaid looks syntactically complete."""
    s = line.strip()
    if not s:
        return True
    # Header lines
    if any(s.lower().startswith(h) for h in _HEADERS):
        return True
    # Keyword lines
    if s.lower() in ("end", "end;"):
        return True
    # Lines ending with common valid endings
    if s.endswith("]") or s.endswith("}") or s.endswith(")") or s.endswith("|"):
        return True
    if s.endswith(":::") or s.endswith(";"):
        return True
    # Arrow lines: must have something after the arrow
    if re.search(r'--[->]\s*\w', s) or re.search(r'==>\s*\w', s):
        return True
    # Subgraph declarations
    if s.lower().startswith("subgraph"):
        return True
    # ER/Class/Sequence lines
    if re.search(r'[{}:]$', s):
        return True
    # participant/actor declarations
    if re.search(r'^(participant|actor)\s+', s, re.I):
        return True
    # Dangling arrow with nothing after
    if re.search(r'--[->]\s*$', s) or re.search(r'==>\s*$', s):
        return False
    # Unclosed bracket
    if s.count("[") > s.count("]") or s.count("{") > s.count("}"):
        return False
    return True


def _deduplicate_edges(code: str) -> str:
    """Remove exact duplicate lines (LLM sometimes repeats edges)."""
    seen = set()
    result = []
    for line in code.splitlines():
        stripped = line.strip()
        # Keep empty lines, headers, subgraph/end — dedup only edge/node lines
        if not stripped or stripped.lower() in ("end",) or any(
            stripped.lower().startswith(h) for h in _HEADERS + ["subgraph"]
        ):
            result.append(line)
            continue
        if stripped in seen:
            continue
        seen.add(stripped)
        result.append(line)
    return "\n".join(result)


def _balance_brackets(line: str, open_char: str, close_char: str) -> str:
    """Add missing closing brackets to a line."""
    opens = line.count(open_char)
    closes = line.count(close_char)
    if opens > closes:
        line += close_char * (opens - closes)
    return line


def _clean_whitespace(code: str) -> str:
    """Normalize indentation and remove trailing spaces."""
    lines = [line.rstrip() for line in code.splitlines()]
    # Remove leading/trailing blank lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  TEMPLATE BUILDER — fallback when LLM output is unusable
# ═══════════════════════════════════════════════════════════

def build_from_entities(
    entities: list[str],
    relationships: list[tuple[str, str, str]],
    diagram_type: str = "flowchart TD",
    title: str = "",
) -> str:
    """
    Build a diagram from extracted entities and relationships.
    entities: ["Entity A", "Entity B", ...]
    relationships: [("A", "B", "label"), ...]
    """
    dt = diagram_type

    if "flowchart" in dt.lower() or "graph" in dt.lower():
        return _build_flowchart(entities, relationships, dt, title)
    if "sequence" in dt.lower():
        return _build_sequence(entities, relationships, title)
    if "mindmap" in dt.lower():
        return _build_mindmap(entities, relationships, title)
    # Default: flowchart
    return _build_flowchart(entities, relationships, dt, title)


def _build_flowchart(entities, relationships, dt, title):
    lines = [dt]
    if title:
        lines.append(f"    %% {title}")

    # Create node IDs from entities
    node_map = {}
    for i, name in enumerate(entities):
        nid = re.sub(r'[^A-Za-z0-9]', '', name)[:12] or f"N{i}"
        if nid in node_map.values():
            nid += str(i)
        node_map[name] = nid
        safe_label = name.replace('"', "'")
        lines.append(f'    {nid}["{safe_label}"]')

    for src, dst, label in relationships:
        sid = node_map.get(src, src)
        did = node_map.get(dst, dst)
        if label:
            safe_lbl = label.replace('"', "'")
            lines.append(f'    {sid} -->|{safe_lbl}| {did}')
        else:
            lines.append(f'    {sid} --> {did}')

    code = "\n".join(lines)
    return f"```mermaid\n{code}\n```"


def _build_sequence(entities, relationships, title):
    lines = ["sequenceDiagram"]
    if title:
        lines.append(f"    %% {title}")

    actors = set()
    for src, dst, label in relationships:
        actors.add(src)
        actors.add(dst)
    for name in entities:
        if name not in actors:
            actors.add(name)

    for actor in sorted(actors):
        safe = actor.replace(" ", "_")
        lines.append(f"    participant {safe} as {actor}")

    for src, dst, label in relationships:
        s = src.replace(" ", "_")
        d = dst.replace(" ", "_")
        lines.append(f"    {s}->>{d}: {label or 'interacts'}")

    code = "\n".join(lines)
    return f"```mermaid\n{code}\n```"


def _build_mindmap(entities, relationships, title):
    root = title or (entities[0] if entities else "Topic")
    lines = ["mindmap", f"  root(({root}))"]

    # Group: use relationships as branches, or just list entities
    if relationships:
        branches = {}
        for src, dst, label in relationships:
            branches.setdefault(src, []).append(dst)
        for branch, leaves in branches.items():
            lines.append(f"    {branch}")
            for leaf in leaves:
                lines.append(f"      {leaf}")
    else:
        for ent in entities[1:] if len(entities) > 1 else entities:
            lines.append(f"    {ent}")

    code = "\n".join(lines)
    return f"```mermaid\n{code}\n```"
