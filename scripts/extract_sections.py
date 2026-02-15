#!/usr/bin/env python3
"""Extract sections from a markdown document for individual review.

Usage: python3 extract_sections.py <plan-file>

Creates .codex-review/sections/ with one file per top-level section.
Each section file includes the document title and TOC as context.
"""

import sys
import re
import shutil
from pathlib import Path


def extract_sections(plan_path: Path) -> list[dict]:
    """Split a markdown file into sections on H2 (or H1 if no H2s) boundaries."""
    content = plan_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    # Extract title (first H1)
    title = "# Untitled Document"
    for line in lines:
        if line.startswith("# ") and not line.startswith("## "):
            title = line
            break

    # Extract TOC if present
    toc_lines = []
    in_toc = False
    for line in lines:
        if re.match(r"^##\s+(table of contents|toc|contents)\s*$", line, re.IGNORECASE):
            in_toc = True
            continue
        if in_toc:
            if line.startswith("## "):
                break
            toc_lines.append(line)

    # Build context header
    context = f"{title}\n\n"
    if toc_lines:
        context += "## Document Structure\n"
        context += "\n".join(toc_lines) + "\n\n"
    context += "---\n"
    context += "*The following is one section from the above document, extracted for focused review.*\n"
    context += "---\n\n"

    # Try splitting on H2 first, then H3, then H1
    sections = _split_on_heading(lines, level=2, title=title)

    # Fall back to H3 if no H2 sections found (common in implementation plans
    # that use ### Task N headers)
    if not sections:
        sections = _split_on_heading(lines, level=3, title=title)

    # Fall back to H1 if no H2 or H3 sections found
    if not sections:
        sections = _split_on_heading(lines, level=1, title=title)

    # Last resort: whole document as one section
    if not sections:
        sections = [{"name": "full-document", "content": content}]

    # Filter out TOC section
    sections = [
        s for s in sections
        if not re.match(r"(table of contents|toc|contents)$", s["name"], re.IGNORECASE)
    ]

    # Prepend context to each section
    for s in sections:
        s["content"] = context + s["content"]

    return sections


def _split_on_heading(lines: list[str], level: int, title: str) -> list[dict]:
    """Split lines into sections based on heading level."""
    prefix = "#" * level + " "
    sections = []
    current_name = None
    current_lines = []

    for line in lines:
        if line.startswith(prefix):
            heading_text = line[len(prefix):].strip()
            # Skip if this is the document title (for H1 splitting)
            if level == 1 and line == title:
                continue
            # Save previous section
            if current_name is not None:
                sections.append({
                    "name": current_name,
                    "content": "\n".join(current_lines),
                })
            current_name = heading_text
            current_lines = [line]
        elif current_name is not None:
            current_lines.append(line)

    # Don't forget the last section
    if current_name is not None:
        sections.append({
            "name": current_name,
            "content": "\n".join(current_lines),
        })

    return sections


def sanitize_filename(name: str) -> str:
    """Convert a section name to a safe filename."""
    safe = re.sub(r"[^a-z0-9]+", "-", name.lower())
    return safe.strip("-")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 extract_sections.py <plan-file>", file=sys.stderr)
        sys.exit(1)

    plan_path = Path(sys.argv[1])
    if not plan_path.is_file():
        print(f"Error: File not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    review_dir = plan_path.parent / ".codex-review"
    sections_dir = review_dir / "sections"

    # Clean previous run
    if sections_dir.exists():
        shutil.rmtree(sections_dir)
    sections_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "feedback" / "pass1").mkdir(parents=True, exist_ok=True)
    (review_dir / "feedback" / "pass2").mkdir(parents=True, exist_ok=True)

    sections = extract_sections(plan_path)

    for i, section in enumerate(sections, 1):
        safe_name = sanitize_filename(section["name"])
        filename = f"{i:02d}-{safe_name}.md"
        out_path = sections_dir / filename
        out_path.write_text(section["content"], encoding="utf-8")

    print(f"Extracted {len(sections)} sections to {sections_dir}")
    for f in sorted(sections_dir.iterdir()):
        if not f.name.startswith("_"):
            print(f"  {f.name}")


if __name__ == "__main__":
    main()
