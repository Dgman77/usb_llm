"""
diagram_engine.py — Graphviz DOT post-processor, validator & auto-repair

Fixes common LLM output issues so DOT diagrams render cleanly via Viz.js.
No external dependencies — pure Python regex + string ops.
"""

import re


# ═══════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════

def process_diagram(raw: str, layout_engine: str = "dot") -> str:
    """
    Main entry: extract DOT code from LLM output, fix common errors,
    return a clean DOT string with no markdown fences.
    """
    code = _extract_dot(raw)
    code = _fix_common_errors(code)
    code = _ensure_digraph_wrapper(code)
    code = _fix_unclosed_braces(code)
    code = _clean_whitespace(code)
    return code


def is_valid(dot_code: str) -> bool:
    """Returns True if string contains 'digraph' or 'graph' and at least one edge (-> or --)."""
    lower = dot_code.lower().strip()
    has_graph = "digraph" in lower or re.search(r'\bgraph\b', lower) is not None
    has_edge = "->" in dot_code or "--" in dot_code
    return has_graph and has_edge


def complexity_score(dot_code: str) -> int:
    """Count nodes + edges, return integer."""
    # Count edges: -> or --
    edges = len(re.findall(r'(?:->|--)', dot_code))
    # Count node definitions: identifiers followed by [ or standalone on a line
    nodes = set()
    for line in dot_code.splitlines():
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        # Skip graph/digraph/subgraph declarations
        if re.match(r'^(di)?graph\b', line, re.I) or line.startswith("subgraph"):
            continue
        # Skip pure attribute lines like node [...], edge [...], rankdir=...
        if re.match(r'^(node|edge|graph)\s*\[', line, re.I):
            continue
        if re.match(r'^(rankdir|ratio|size|label|fontname|fontsize|bgcolor|compound)\s*=', line, re.I):
            continue
        # Edge lines: extract both sides
        edge_match = re.findall(r'([A-Za-z_]\w*)\s*(?:->|--)', line)
        edge_match2 = re.findall(r'(?:->|--)\s*([A-Za-z_]\w*)', line)
        for n in edge_match + edge_match2:
            if n.lower() not in ("node", "edge", "graph", "digraph", "subgraph"):
                nodes.add(n)
        # Node definition: ID [...]
        node_def = re.match(r'^([A-Za-z_]\w*)\s*\[', line)
        if node_def:
            nid = node_def.group(1)
            if nid.lower() not in ("node", "edge", "graph", "digraph", "subgraph"):
                nodes.add(nid)
    return len(nodes) + edges


def build_from_entities(
    entities: list,
    relationships: list,
    layout_engine: str = "dot",
    title: str = "",
) -> str:
    """
    Fallback builder: create a valid DOT string from extracted entities and relationships.
    entities: ["Entity A", "Entity B", ...]
    relationships: [("A", "B", "label"), ...]
    """
    lines = ["digraph G {"]
    lines.append('    rankdir=TB;')
    lines.append('    node [shape=box, style="rounded,filled", fillcolor="#faf6ee", fontname="Arial", fontsize=12];')
    lines.append('    edge [fontname="Arial", fontsize=11, fontcolor="#333333"];')

    if title:
        lines.append(f'    label="{_safe_label(title)}";')
        lines.append('    labelloc=t;')
        lines.append('    fontsize=16;')

    # Create safe node IDs from entities
    node_map = {}
    for i, name in enumerate(entities):
        nid = re.sub(r'[^A-Za-z0-9_]', '', name.replace(' ', '_'))[:20] or f"N{i}"
        if nid in node_map.values():
            nid += str(i)
        node_map[name] = nid
        lines.append(f'    {nid} [label="{_safe_label(name)}"];')

    for src, dst, label in relationships:
        sid = node_map.get(src, re.sub(r'[^A-Za-z0-9_]', '', src.replace(' ', '_'))[:20])
        did = node_map.get(dst, re.sub(r'[^A-Za-z0-9_]', '', dst.replace(' ', '_'))[:20])
        if label:
            lines.append(f'    {sid} -> {did} [label="{_safe_label(label)}"];')
        else:
            lines.append(f'    {sid} -> {did};')

    lines.append("}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
#  INTERNALS
# ═══════════════════════════════════════════════════════════

def _safe_label(text: str) -> str:
    """Escape quotes and backslashes for DOT labels."""
    return text.replace('\\', '\\\\').replace('"', '\\"')


def _extract_dot(raw: str) -> str:
    """Pull DOT code out of markdown fences / surrounding text."""
    # ```dot ... ``` or ```graphviz ... ```
    m = re.search(r'```(?:dot|graphviz)\s*\n?([\s\S]*?)```', raw, re.I)
    if m:
        return m.group(1).strip()

    # ``` ... ``` (generic fenced block containing digraph/graph)
    m = re.search(r'```\s*\n?([\s\S]*?)```', raw, re.I)
    if m:
        inner = m.group(1).strip()
        if 'digraph' in inner.lower() or re.search(r'\bgraph\b', inner, re.I):
            return inner

    # No fences — look for digraph or graph keyword
    for line_no, line in enumerate(raw.splitlines()):
        stripped = line.strip().lower()
        if stripped.startswith("digraph") or re.match(r'^graph\b', stripped):
            return "\n".join(raw.splitlines()[line_no:]).strip()

    return raw.strip()


def _fix_common_errors(code: str) -> str:
    """Fix the most common LLM-generated DOT errors."""
    lines = code.splitlines()
    fixed = []

    for line in lines:
        original = line
        line = line.rstrip()

        # Skip empty lines early
        if not line.strip():
            fixed.append(line)
            continue

        # Fix: smart quotes → straight quotes
        line = line.replace("\u201c", '"').replace("\u201d", '"')
        line = line.replace("\u2018", "'").replace("\u2019", "'")

        # Fix: em-dash / en-dash → regular dashes
        line = line.replace("\u2014", "--").replace("\u2013", "--")

        # Fix: HTML entities that sneak in
        line = line.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")

        # Fix: invalid attribute syntax — color: red → color="red"
        line = re.sub(
            r'(\w+)\s*:\s*([^,\]\};"]+?)(?=[,\]\};]|$)',
            lambda m: f'{m.group(1)}="{m.group(2).strip()}"'
            if m.group(1).lower() in ("color", "fillcolor", "fontcolor", "style", "shape", "fontname", "fontsize", "label", "xlabel", "tooltip", "width", "height", "penwidth")
            and "=" not in m.group(0)
            else m.group(0),
            line,
        )

        # Fix: missing semicolons at end of statement lines
        stripped = line.strip()
        if stripped and not stripped.startswith("//") and not stripped.startswith("#"):
            # Lines that should end with ; or { or }
            if stripped.endswith("]") and not stripped.endswith("};"):
                line = line.rstrip() + ";"
            elif re.match(r'^[A-Za-z_]\w*\s*->\s*[A-Za-z_]\w*\s*$', stripped):
                # bare edge like A -> B without semicolon
                line = line.rstrip() + ";"

        fixed.append(line)

    return "\n".join(fixed)


def _ensure_digraph_wrapper(code: str) -> str:
    """Make sure the code has a digraph or graph wrapper."""
    stripped = code.strip()
    # Already has wrapper
    if re.match(r'^(strict\s+)?(di)?graph\b', stripped, re.I):
        return code
    # Wrap in digraph
    return f"digraph G {{\n{code}\n}}"


def _fix_unclosed_braces(code: str) -> str:
    """Close any unclosed braces."""
    open_count = code.count("{")
    close_count = code.count("}")
    if open_count > close_count:
        code += "\n}" * (open_count - close_count)
    return code


def _clean_whitespace(code: str) -> str:
    """Normalize indentation and remove trailing spaces."""
    lines = [line.rstrip() for line in code.splitlines()]
    # Remove leading/trailing blank lines
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)
