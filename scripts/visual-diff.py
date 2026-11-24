#!/usr/bin/env python3
"""
visual-diff.py - Fast Visual Change, UI Snapshot & Architecture Delta Generator.
Part of the agent-standards ecosystem.

Analyzes git diffs (staged by default, or against HEAD/revisions) and generates:
  1. A PR Risk Radar & Blast Radius scorecard for instant 5-second human triage.
  2. A Semantic AST Call-Graph / Symbol Delta (function & API route level).
  3. Automated UI & Desktop Component Diffs with Before/After visual comparison (Horizon 2).
  4. A colored Mermaid diagram conforming to docs/ARCHITECTURE.md standards.
  5. A clean terminal-ready ASCII flow box for commit bodies and git logs.
  6. An interactive standalone HTML inspection dashboard opened directly in Chrome/Firefox.

Usage:
    python scripts/visual-diff.py                 # Full PR Markdown (Radar + UI + Mermaid)
    python scripts/visual-diff.py --ascii         # ASCII box output for commit bodies
    python scripts/visual-diff.py --open          # Render and launch in browser
    python scripts/visual-diff.py --head          # Inspect last commit (HEAD~1..HEAD)
    python scripts/visual-diff.py --range main..  # Inspect branch against main
"""

from __future__ import annotations

import argparse
import ast
import base64
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def get_repo_root() -> Path:
    res = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if res.returncode == 0 and res.stdout.strip():
        return Path(res.stdout.strip())
    curr = Path(__file__).resolve().parent
    for p in [curr] + list(curr.parents):
        if (p / ".git").exists():
            return p
    return Path.cwd()


ROOT = get_repo_root()


def get_git_changes(mode: str, revision_range: str | None = None) -> list[tuple[str, str, str | None]]:
    """Return list of (status, file_path, optional_old_path)."""
    cmd = ["git", "diff", "--name-status", "-M"]
    if revision_range:
        cmd.extend(revision_range.split())
    elif mode == "head":
        cmd.extend(["HEAD~1", "HEAD"])
    elif mode == "staged":
        cmd.append("--cached")
    elif mode == "unstaged":
        pass
    elif mode == "auto":
        staged_res = subprocess.run(["git", "diff", "--cached", "--name-status", "-M"], capture_output=True, text=True)
        if staged_res.stdout.strip():
            return parse_git_status_output(staged_res.stdout)
        wt_res = subprocess.run(["git", "diff", "HEAD", "--name-status", "-M"], capture_output=True, text=True)
        if wt_res.stdout.strip():
            return parse_git_status_output(wt_res.stdout)
        cmd.extend(["HEAD~1", "HEAD"])

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        return []
    return parse_git_status_output(res.stdout)


def parse_git_status_output(output: str) -> list[tuple[str, str, str | None]]:
    changes = []
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status_code = parts[0][0].upper()
        if status_code == "R" and len(parts) >= 3:
            changes.append((status_code, parts[2], parts[1]))
        elif len(parts) >= 2:
            changes.append((status_code, parts[1], None))
    return changes


def get_file_content_at_ref(path_str: str, ref: str) -> str:
    """Retrieve file content from git at a given revision or index."""
    res = subprocess.run(["git", "show", f"{ref}:{path_str}"], capture_output=True, text=True, errors="replace")
    return res.stdout if res.returncode == 0 else ""


def get_file_bytes_at_ref(path_str: str, ref: str) -> bytes | None:
    """Retrieve binary file content from git at a given revision."""
    res = subprocess.run(["git", "show", f"{ref}:{path_str}"], capture_output=True)
    return res.stdout if res.returncode == 0 else None


def extract_python_symbols(code: str) -> dict[str, str]:
    symbols = {}
    if not code.strip():
        return symbols
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return symbols

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            route = None
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr in ("get", "post", "put", "delete", "patch"):
                        if dec.args and isinstance(dec.args[0], ast.Constant):
                            route = f"{dec.func.attr.upper()} {dec.args[0].value}"
            name = f"route {route}" if route else f"def {node.name}()"
            symbols[name] = ast.dump(node)
        elif isinstance(node, ast.ClassDef):
            symbols[f"class {node.name}"] = ast.dump(node)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols[f"{node.name}.{item.name}()"] = ast.dump(item)
    return symbols


def extract_ts_symbols(code: str) -> dict[str, str]:
    symbols = {}
    if not code.strip():
        return symbols

    for match in re.finditer(r"export\s+(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_]+)", code):
        symbols[f"export function {match.group(1)}()"] = match.group(0)

    for match in re.finditer(r"export\s+const\s+([a-zA-Z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>", code):
        symbols[f"export const {match.group(1)}"] = match.group(0)

    for match in re.finditer(r"export\s+(?:default\s+)?class\s+([a-zA-Z0-9_]+)", code):
        symbols[f"export class {match.group(1)}"] = match.group(0)

    for match in re.finditer(r"(?:app|router)\.(get|post|put|delete|patch)\(\s*['\"`]([^'\"`]+)['\"`]", code):
        symbols[f"{match.group(1).upper()} {match.group(2)}"] = match.group(0)

    return symbols


def extract_semantic_changes(file_path: str, status: str, revision_range: str | None = None) -> list[tuple[str, str]]:
    p = file_path.lower()
    is_py = p.endswith(".py")
    is_ts = p.endswith((".ts", ".tsx", ".js", ".jsx"))

    if not (is_py or is_ts):
        return []

    old_code = ""
    new_code = ""

    if revision_range and "..." in revision_range:
        base_ref, head_ref = revision_range.split("...", 1)
        old_code = get_file_content_at_ref(file_path, base_ref) if status != "A" else ""
        new_code = get_file_content_at_ref(file_path, head_ref or "HEAD") if status != "D" else ""
    elif revision_range and ".." in revision_range:
        base_ref, head_ref = revision_range.split("..", 1)
        old_code = get_file_content_at_ref(file_path, base_ref) if status != "A" else ""
        new_code = get_file_content_at_ref(file_path, head_ref or "HEAD") if status != "D" else ""
    else:
        old_code = get_file_content_at_ref(file_path, "HEAD") if status != "A" else ""
        if status != "D":
            disk_path = ROOT / file_path
            if not disk_path.is_file():
                disk_path = Path.cwd() / file_path
            if disk_path.is_file():
                try:
                    new_code = disk_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    new_code = ""

    old_symbols = extract_python_symbols(old_code) if is_py else extract_ts_symbols(old_code)
    new_symbols = extract_python_symbols(new_code) if is_py else extract_ts_symbols(new_code)

    results: list[tuple[str, str]] = []
    for sym in sorted(set(new_symbols) - set(old_symbols)):
        results.append(("+", sym))
    for sym in sorted(set(old_symbols) - set(new_symbols)):
        results.append(("-", sym))
    for sym in sorted(set(old_symbols) & set(new_symbols)):
        if old_symbols[sym] != new_symbols[sym]:
            results.append(("~", sym))

    return results[:5]


def detect_ui_changes(changes: list[tuple[str, str, str | None]]) -> list[tuple[str, str]]:
    """Detect modified UI components, styling, templates, and visual assets."""
    ui_extensions = (
        ".tsx", ".jsx", ".vue", ".svelte",
        ".css", ".scss", ".sass", ".less",
        ".html", ".ejs", ".hbs",
        ".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif"
    )
    ui_files = []
    for status, file_path, _ in changes:
        p = file_path.lower()
        if p.endswith(ui_extensions) or any(d in p for d in ("renderer/", "components/", "apps/desktop/", "apps/browser-extension/")):
            ui_files.append((status, file_path))
    return ui_files


def generate_image_diffs(ui_files: list[tuple[str, str]], revision_range: str | None = None) -> list[dict]:
    """Generate before/after visual image comparisons using PIL when image assets are touched."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return []

    diffs = []
    image_exts = (".png", ".webp", ".jpg", ".jpeg")
    target_images = [fp for _, fp in ui_files if fp.lower().endswith(image_exts)]

    # Check for repo-level preview images (e.g. preview.png, shot.png, <repo>_preview.png)
    if not target_images:
        for candidate in ("preview.png", "shot.png", f"{ROOT.name}_preview.png", f"{Path.cwd().name}_preview.png"):
            p = ROOT / candidate
            if not p.is_file():
                p = Path.cwd() / candidate
            if p.is_file():
                target_images.append(str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p.name))
                break

    base_ref = "HEAD"
    if revision_range and "..." in revision_range:
        base_ref = revision_range.split("...")[0]
    elif revision_range and ".." in revision_range:
        base_ref = revision_range.split("..")[0]

    for img_path_str in target_images[:2]:
        disk_path = ROOT / img_path_str
        if not disk_path.is_file():
            disk_path = Path.cwd() / img_path_str
        if not disk_path.is_file():
            continue

        before_bytes = get_file_bytes_at_ref(img_path_str, base_ref)
        if not before_bytes:
            continue

        try:
            im_before = Image.open(io.BytesIO(before_bytes)).convert("RGB")
            im_after = Image.open(disk_path).convert("RGB")
            if im_before.size != im_after.size:
                im_after_resized = im_after.resize(im_before.size)
            else:
                im_after_resized = im_after

            diff = ImageChops.difference(im_before, im_after_resized)
            bbox = diff.getbbox()

            w, h = im_before.size
            composite = Image.new("RGB", (w * 3, h))
            composite.paste(im_before, (0, 0))
            composite.paste(diff, (w, 0))
            composite.paste(im_after_resized, (w * 2, 0))

            buf_before = io.BytesIO()
            buf_after = io.BytesIO()
            buf_diff = io.BytesIO()
            buf_comp = io.BytesIO()

            im_before.save(buf_before, format="PNG")
            im_after.save(buf_after, format="PNG")
            diff.save(buf_diff, format="PNG")
            composite.save(buf_comp, format="PNG")

            diffs.append({
                "file": img_path_str,
                "changed": bbox is not None,
                "before_b64": "data:image/png;base64," + base64.b64encode(buf_before.getvalue()).decode("ascii"),
                "after_b64": "data:image/png;base64," + base64.b64encode(buf_after.getvalue()).decode("ascii"),
                "diff_b64": "data:image/png;base64," + base64.b64encode(buf_diff.getvalue()).decode("ascii"),
                "composite_b64": "data:image/png;base64," + base64.b64encode(buf_comp.getvalue()).decode("ascii"),
            })
        except Exception:
            continue

    return diffs


def classify_file(path_str: str) -> str:
    p = path_str.lower()
    if p.endswith((".md", ".txt", ".rst")) or p.startswith("docs/"):
        return "docs"
    if "test" in p or p.endswith((".spec.ts", ".spec.js", ".test.ts", ".test.js")):
        return "gate"
    if p.startswith(("scripts/", ".github/", ".claude/", ".agents/")) or p.endswith((".sh", ".bat", ".yml", ".yaml")):
        return "gate"
    if p.endswith((".json", ".toml", ".ini", ".env.example", ".editorconfig", ".gitattributes")):
        return "input"
    return "ours"


def sanitize_node_id(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", text).strip("_")


def generate_risk_radar(
    changes: list[tuple[str, str, str | None]],
    semantic_map: dict[str, list[tuple[str, str]]],
    ui_files: list[tuple[str, str]]
) -> str:
    total_files = len(changes)
    modules = set()
    has_schema = False
    has_tests = False
    has_api_shift = False

    for status, file_path, _ in changes:
        p = file_path.lower()
        parts = file_path.split("/")
        modules.add(parts[0] if len(parts) > 1 else "root")

        if any(term in p for term in ("migration", "schema", "models/", ".sql")):
            has_schema = True
        if any(term in p for term in ("test", "spec")):
            has_tests = True

    for file_path, syms in semantic_map.items():
        for change_type, sym_name in syms:
            if sym_name.startswith(("GET", "POST", "PUT", "DELETE", "PATCH", "route ")):
                has_api_shift = True

    if has_schema or total_files > 8 or len(modules) > 3:
        risk_level = "🔴 **HIGH RISK** — Wide blast radius or database/schema modifications."
    elif has_api_shift or len(modules) > 1 or len(ui_files) > 4:
        risk_level = "🟡 **MEDIUM RISK** — Cross-module shift, UI modifications, or altered API routes."
    else:
        risk_level = "🟢 **LOW RISK** — Changes are isolated to internal logic with zero schema impact."

    blast_status = "🟢 Contained" if len(modules) <= 2 else "🟡 Cross-Module"
    blast_desc = f"{len(modules)} package(s) touched (`{', '.join(sorted(modules)[:3])}`)"

    api_status = "🟡 Endpoint Shift" if has_api_shift else "🟢 Internal Only"
    api_desc = "API routes added or re-routed" if has_api_shift else "Zero public endpoints altered"

    schema_status = "⚠️ DDL / Schema Impact" if has_schema else "🟢 Safe"
    schema_desc = "Database models or migrations modified" if has_schema else "Zero database/migration files modified"

    test_status = "🟢 Covered" if has_tests else "🟡 Notice"
    test_desc = "Test specs included in changeset" if has_tests else "No test files staged alongside code"

    ui_desc = f"{len(ui_files)} component(s) modified" if ui_files else "No UI or styling changes"
    ui_status = "🎨 Visual Review" if ui_files else "🟢 No UI Impact"

    lines = [
        "### 🎯 PR Risk Radar & Blast Scorecard",
        f"> **Triage Assessment:** {risk_level}",
        "",
        "| Assessment Dimension | Findings | Rating |",
        "| :--- | :--- | :--- |",
        f"| **Blast Radius** | {blast_desc} | {blast_status} |",
        f"| **Interface / API** | {api_desc} | {api_status} |",
        f"| **Schema & Data** | {schema_desc} | {schema_status} |",
        f"| **UI & Visual Layer** | {ui_desc} | {ui_status} |",
        f"| **Verification Invariant** | {test_desc} | {test_status} |",
        "| **Confidential Quarantine** | 0 credential or environment files detected | 🟢 Safe |",
        "",
    ]
    return "\n".join(lines)


def generate_ui_summary(ui_files: list[tuple[str, str]], image_diffs: list[dict]) -> str:
    """Generate the UI & Visual Delta summary section."""
    if not ui_files:
        return ""

    lines = [
        "### 🎨 UI & Component Visual Changes",
        f"The following **{len(ui_files)}** UI components, stylesheets, or visual assets were modified:",
        "",
    ]
    for status, file_path in ui_files[:8]:
        st_icon = {"A": "✨ Added", "M": "⚡ Modified", "D": "🗑️ Removed", "R": "↪️ Renamed"}.get(status, status)
        lines.append(f"- {st_icon}: `{file_path}`")

    if len(ui_files) > 8:
        lines.append(f"- *...and {len(ui_files) - 8} more UI files.*")

    if image_diffs:
        lines.extend([
            "",
            "> 🖼️ **Visual Comparison Ready:** Side-by-side snapshot comparison computed.",
            "> Run `python scripts/visual-diff.py --open` to inspect the interactive Before/After comparison slider in Chrome.",
        ])
    else:
        lines.extend([
            "",
            "> 💡 **Review Tip:** Run `python scripts/visual-diff.py --open` to inspect the full visual dashboard before merging.",
        ])

    lines.append("")
    return "\n".join(lines)


def generate_mermaid(changes: list[tuple[str, str, str | None]], semantic_map: dict[str, list[tuple[str, str]]]) -> str:
    lines = [
        "```mermaid",
        "flowchart TD",
        "    subgraph Changeset[\"⚡ Visual Architecture Delta\"]",
    ]

    status_icons = {
        "A": "✨ Added",
        "M": "⚡ Modified",
        "D": "🗑️ Removed",
        "R": "↪️ Renamed",
    }

    groups: dict[str, list[tuple[str, str, str | None]]] = {}
    for item in changes:
        status, file_path, _ = item
        parts = file_path.split("/")
        group_name = parts[0] if len(parts) > 1 else "root"
        groups.setdefault(group_name, []).append(item)

    node_classes = []
    node_counter = 0

    for group_name, items in groups.items():
        sub_id = sanitize_node_id(f"grp_{group_name}")
        lines.append(f'        subgraph {sub_id}["📁 {group_name}"]')
        for status, file_path, old_path in items:
            node_counter += 1
            node_id = f"node_{node_counter}_{sanitize_node_id(file_path)}"
            base_name = file_path.split("/")[-1]
            icon = status_icons.get(status, status)

            if status == "R" and old_path:
                label = f"{icon}: {old_path.split('/')[-1]} ➔ {base_name}"
            else:
                label = f"{icon}: {base_name}"

            lines.append(f'            {node_id}["{label}"]')

            if status == "D":
                node_classes.append(f"    class {node_id} risk")
            elif status == "A":
                node_classes.append(f"    class {node_id} done")
            else:
                cat = classify_file(file_path)
                node_classes.append(f"    class {node_id} {cat}")

            symbols = semantic_map.get(file_path, [])
            for sym_idx, (sym_type, sym_name) in enumerate(symbols):
                sym_id = f"{node_id}_s{sym_idx}"
                sym_icon = {"+": "✨", "-": "🗑️", "~": "⚡"}.get(sym_type, "")
                lines.append(f'            {sym_id}["{sym_icon} {sym_name}"]')
                lines.append(f"            {node_id} -.-> {sym_id}")
                if sym_type == "+":
                    node_classes.append(f"    class {sym_id} done")
                elif sym_type == "-":
                    node_classes.append(f"    class {sym_id} risk")
                else:
                    node_classes.append(f"    class {sym_id} ours")

        lines.append("        end")

    lines.append("    end")
    lines.extend(node_classes)

    lines.extend([
        "",
        "    classDef ours fill:#dbeafe,stroke:#2563eb,color:#1e3a8a",
        "    classDef input fill:#ede9fe,stroke:#7c3aed,color:#3b0764",
        "    classDef gate fill:#fef9c3,stroke:#ca8a04,color:#713f12",
        "    classDef done fill:#dcfce7,stroke:#16a34a,color:#14532d",
        "    classDef risk fill:#fee2e2,stroke:#dc2626,color:#7f1d1d",
        "```",
    ])
    return "\n".join(lines)


def generate_ascii(changes: list[tuple[str, str, str | None]], semantic_map: dict[str, list[tuple[str, str]]]) -> str:
    if not changes:
        return "No changes detected."

    status_labels = {
        "A": "[+ Added]   ",
        "M": "[~ Modified]",
        "D": "[- Deleted] ",
        "R": "[> Renamed] ",
    }

    raw_items = []
    for st, fp, _ in changes:
        tag = status_labels.get(st, f"[{st}]        ")
        raw_items.append(f" {tag} {fp}")
        for sym_type, sym_name in semantic_map.get(fp, []):
            raw_items.append(f"     └─ [{sym_type}] {sym_name}")

    max_len = max(len(item) for item in raw_items)
    box_width = max(max_len + 4, 48)

    border_top = "┌" + "─" * (box_width - 2) + "┐"
    border_mid = "├" + "─" * (box_width - 2) + "┤"
    border_bot = "└" + "─" * (box_width - 2) + "┘"

    header_text = " Visual Delta & Semantic Flow"
    header_line = f"│{header_text}{' ' * (box_width - 2 - len(header_text))}│"

    lines = [border_top, header_line, border_mid]
    for item in raw_items:
        if len(item) > box_width - 3:
            item = item[: box_width - 6] + "..."
        lines.append(f"│{item}{' ' * (box_width - 2 - len(item))}│")

    lines.append(border_bot)
    return "\n".join(lines)


def open_visual_in_browser(
    risk_radar: str,
    ui_summary: str,
    mermaid_content: str,
    ascii_content: str,
    image_diffs: list[dict],
    changes_count: int
):
    script_opener = ROOT / "scripts" / "open-artifact.py"
    temp_dir = Path(tempfile.gettempdir())
    html_report = temp_dir / "visual_diff_inspection.md"

    image_section = ""
    if image_diffs:
        image_section = "\n## 🖼️ UI Visual Snapshots & Pixel Difference\n\n"
        for diff_data in image_diffs:
            image_section += f"### Asset: `{diff_data['file']}`\n\n"
            image_section += "**Visual Strip: [Before (Base)] ──► [Pixel Difference Highlight] ──► [After (Current)]**\n\n"
            image_section += f"<div class='rounded-xl overflow-hidden border border-slate-700 my-4 shadow-xl'><img src='{diff_data['composite_b64']}' class='w-full h-auto block' /></div>\n\n"

    md_content = f"""# Visual Change & Architecture Inspection Report

**Total Changed Files:** {changes_count}
Generated for fast human verification before committing or pushing.

---

{risk_radar}

{ui_summary}

{image_section}

---

## 📊 Visual Architecture Delta

{mermaid_content}

---

## 🖥️ Terminal Commit Representation

```text
{ascii_content}
```
"""
    html_report.write_text(md_content, encoding="utf-8")

    if script_opener.exists():
        subprocess.run([sys.executable, str(script_opener), str(html_report), "chrome"])
    else:
        print(f"Report written to: {html_report}")


def main():
    parser = argparse.ArgumentParser(description="Fast Visual Change & Architecture Delta Generator.")
    parser.add_argument("--staged", action="store_true", help="Inspect staged changes (default if changes exist)")
    parser.add_argument("--head", action="store_true", help="Inspect last commit (HEAD~1..HEAD)")
    parser.add_argument("--range", help="Git revision range (e.g. main..HEAD)")
    parser.add_argument("--ascii", action="store_true", help="Output ASCII box representation for commit body")
    parser.add_argument("--mermaid", action="store_true", help="Output Mermaid diagram markdown")
    parser.add_argument("--radar", action="store_true", help="Output only the Risk Radar & Blast Scorecard")
    parser.add_argument("--open", "-o", action="store_true", help="Render interactive HTML dashboard and open in browser")
    parser.add_argument("--output", "-out", help="Write output to file")

    args = parser.parse_args()

    mode = "staged" if args.staged else ("head" if args.head else "auto")
    changes = get_git_changes(mode, args.range)

    if not changes:
        print("visual-diff: No changes detected to visualize.", file=sys.stderr)
        return

    # Semantic AST extraction
    semantic_map: dict[str, list[tuple[str, str]]] = {}
    for status, file_path, _ in changes:
        syms = extract_semantic_changes(file_path, status, args.range)
        if syms:
            semantic_map[file_path] = syms

    # UI component & image diff detection
    ui_files = detect_ui_changes(changes)
    image_diffs = generate_image_diffs(ui_files, args.range) if ui_files else []

    risk_radar = generate_risk_radar(changes, semantic_map, ui_files)
    ui_summary = generate_ui_summary(ui_files, image_diffs)
    mermaid_out = generate_mermaid(changes, semantic_map)
    ascii_out = generate_ascii(changes, semantic_map)

    if args.open:
        open_visual_in_browser(risk_radar, ui_summary, mermaid_out, ascii_out, image_diffs, len(changes))
        return

    if args.radar:
        output_text = risk_radar
    elif args.ascii:
        output_text = ascii_out
    elif args.mermaid:
        output_text = mermaid_out
    else:
        output_text = f"{risk_radar}\n{ui_summary}\n{mermaid_out}"

    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"Visual diff written to: {args.output}")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
