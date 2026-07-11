"""
diagram_engine.py — Graphviz DOT post-processor, validator & auto-repair

Fixes common LLM output issues so DOT diagrams render cleanly via Viz.js.
No external dependencies — pure Python regex + string ops.
"""

import re


# ═══════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════

def process_diagram(raw: str, layout_engine: str = "dot", prompt: str = "") -> str:
    """
    Main entry: extract DOT code from LLM output, fix common errors,
    return a clean DOT string with no markdown fences.
    """
    code = _extract_dot(raw)
    code = _fix_common_errors(code)
    code = _ensure_digraph_wrapper(code)
    code = _fix_unclosed_braces(code)
    code = _clean_whitespace(code)
    if prompt:
        code = strip_unrelated_example_subgraphs(code, prompt)
        code = strip_loose_example_nodes(code, prompt)
        code = clean_unrelated_frontend_labels(code, prompt)
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
    lines.append('    node [shape=box, style="rounded,filled", fillcolor="#cbd5e1", fontname="Arial", fontsize=12];')
    lines.append('    edge [fontname="Arial", fontsize=11, fontcolor="#000000"];')

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


def strip_unrelated_example_subgraphs(dot_code: str, prompt: str) -> str:
    """Remove cluster subgraphs of examples if they are not mentioned in prompt."""
    examples = ["frontend", "checkout", "fulfillment"]
    for ex in examples:
        if ex not in prompt.lower():
            dot_code = _strip_subgraph(dot_code, ex)
    return dot_code


def _strip_subgraph(dot_code: str, name: str) -> str:
    pattern = r'subgraph\s+(?:cluster_)?' + re.escape(name) + r'\b'
    if not re.search(pattern, dot_code, re.I):
        return dot_code

    lines = dot_code.splitlines()
    new_lines = []
    in_subgraph = False
    brace_depth = 0
    subgraph_brace_depth = -1

    for line in lines:
        stripped = line.strip()
        
        if not in_subgraph and re.match(r'^subgraph\s+(?:cluster_)?' + re.escape(name) + r'\b', stripped, re.I):
            in_subgraph = True
            line_opens = line.count('{')
            line_closes = line.count('}')
            brace_depth += line_opens - line_closes
            subgraph_brace_depth = brace_depth
            continue
            
        line_opens = line.count('{')
        line_closes = line.count('}')
        
        if in_subgraph:
            # Skip the label line specifying label="Name"
            if re.match(r'^label\s*=\s*["\']?' + re.escape(name) + r'["\']?\s*;?$', stripped, re.I):
                continue
            
            brace_depth += line_opens - line_closes
            
            if brace_depth < subgraph_brace_depth:
                in_subgraph = False
                subgraph_brace_depth = -1
                continue
                
            new_lines.append(line)
        else:
            brace_depth += line_opens - line_closes
            new_lines.append(line)
            
    return "\n".join(new_lines)


def clean_unrelated_frontend_labels(dot_code: str, prompt: str) -> str:
    """
    Rename 'frontend' label terms to 'client' or 'interface' if frontend is not in the prompt.
    """
    if "frontend" in prompt.lower():
        return dot_code
        
    dot_code = re.sub(r'\biOS\s+frontend\b', 'iOS client', dot_code, flags=re.I)
    dot_code = re.sub(r'\bAndroid\s+frontend\b', 'Android client', dot_code, flags=re.I)
    dot_code = re.sub(r'\bfrontend\b', 'client', dot_code, flags=re.I)
    dot_code = re.sub(r'\bFrontend\b', 'Client', dot_code)
    return dot_code


# ── Known example boilerplate labels that should NEVER appear in user diagrams ──
# These are exact lower-cased label strings from the example prompt in DIAGRAM_PROMPTS.
_EXAMPLE_NODE_LABELS_EXACT = {
    # Old shopping example
    "customer opens product page",
    "add item to shopping cart",
    "cart has 3+ items?",
    "show bulk discount",
    "standard pricing",
    "enter shipping address",
    "select payment method",
    "credit card valid?",
    "process payment via stripe",
    "display card error",
    "generate order confirmation",
    "send confirmation email",
    "update inventory database",
    # New layer example
    "source system a",
    "source system b",
    "data collector",
    "validation engine",
    "enrichment service",
}


def strip_loose_example_nodes(dot_code: str, prompt: str) -> str:
    """
    Remove node definitions and their connected edges that:
    1. Appear OUTSIDE any subgraph cluster (i.e., are loose/free-floating), AND
    2. Have labels exactly matching known example boilerplate labels.
    """
    # Collect IDs of all nodes inside a subgraph
    subgraph_node_ids = set()
    brace_depth = 0
    in_subgraph = False
    subgraph_depth_start = -1
    for line in dot_code.splitlines():
        stripped = line.strip()
        opens = line.count('{')
        closes = line.count('}')
        brace_depth += opens - closes

        if re.match(r'^subgraph\s+cluster_', stripped, re.I):
            in_subgraph = True
            subgraph_depth_start = brace_depth

        if in_subgraph:
            node_m = re.match(r'^([A-Za-z_][\w]*)\s*\[', stripped)
            if node_m:
                subgraph_node_ids.add(node_m.group(1))
            if brace_depth < subgraph_depth_start:
                in_subgraph = False
                subgraph_depth_start = -1

    # Find loose node IDs whose labels exactly match known boilerplate
    bad_node_ids = set()
    brace_depth = 0
    in_subgraph = False
    subgraph_depth_start = -1
    for line in dot_code.splitlines():
        stripped = line.strip()
        opens = line.count('{')
        closes = line.count('}')
        brace_depth += opens - closes

        if re.match(r'^subgraph\s+cluster_', stripped, re.I):
            in_subgraph = True
            subgraph_depth_start = brace_depth
        if in_subgraph and brace_depth < subgraph_depth_start:
            in_subgraph = False
            subgraph_depth_start = -1

        if not in_subgraph:
            node_m = re.match(r'^([A-Za-z_][\w]*)\s*\[([^\]]*)\]', stripped)
            if node_m:
                node_id = node_m.group(1)
                attrs = node_m.group(2)
                label_m = re.search(r'label\s*=\s*"([^"]+)"', attrs, re.I)
                if label_m:
                    label_text = label_m.group(1).lower().strip()
                    if label_text in _EXAMPLE_NODE_LABELS_EXACT:
                        bad_node_ids.add(node_id)

    if not bad_node_ids:
        return dot_code

    print(f"[DiagramEngine] Stripping {len(bad_node_ids)} loose example nodes: {bad_node_ids}")

    # Remove lines that define or solely reference bad nodes
    new_lines = []
    brace_depth = 0
    in_subgraph = False
    subgraph_depth_start = -1
    for line in dot_code.splitlines():
        stripped = line.strip()
        opens = line.count('{')
        closes = line.count('}')
        brace_depth += opens - closes

        if re.match(r'^subgraph\s+cluster_', stripped, re.I):
            in_subgraph = True
            subgraph_depth_start = brace_depth
        if in_subgraph and brace_depth < subgraph_depth_start:
            in_subgraph = False
            subgraph_depth_start = -1

        if in_subgraph:
            new_lines.append(line)
            continue

        # Skip node definition lines for bad nodes
        node_def_m = re.match(r'^([A-Za-z_][\w]*)\s*\[', stripped)
        if node_def_m and node_def_m.group(1) in bad_node_ids:
            continue

        # Skip edge lines where BOTH endpoints are bad nodes or one is bad & other not in any subgraph
        edge_m = re.match(r'^([A-Za-z_][\w]*)\s*->\s*([A-Za-z_][\w]*)', stripped)
        if edge_m:
            src, dst = edge_m.group(1), edge_m.group(2)
            if src in bad_node_ids and dst in bad_node_ids:
                continue
            if src in bad_node_ids and dst not in subgraph_node_ids:
                continue
            if dst in bad_node_ids and src not in subgraph_node_ids:
                continue

        new_lines.append(line)

    return "\n".join(new_lines)
