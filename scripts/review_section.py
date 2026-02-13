#!/usr/bin/env python3
"""Invoke Codex to review a single section of a design document.

Usage: python review_section.py <section-file> [review-type]
review-type: architecture (default), implementation, api, data
"""

import sys
import subprocess
import os
from pathlib import Path
from datetime import datetime, timezone


def find_codex() -> str:
    """Find the codex executable, handling Windows npm quirks."""
    import shutil

    # Try direct lookup first
    codex_path = shutil.which("codex")
    if codex_path:
        return codex_path

    # On Windows, npm installs a .cmd wrapper that shutil.which may miss
    if sys.platform == "win32":
        codex_path = shutil.which("codex.cmd")
        if codex_path:
            return codex_path

    return ""


def run_codex(prompt: str, timeout: int, model: str | None = None, verbose: bool = False) -> str:
    """Run codex exec, piping the prompt via stdin to avoid CLI length limits."""
    codex_bin = find_codex()
    use_shell = sys.platform == "win32" and not codex_bin

    if codex_bin:
        cmd = [codex_bin, "exec", "--ephemeral"]
    else:
        cmd = ["codex", "exec", "--ephemeral"]

    if model:
        cmd.extend(["-m", model])
    cmd.append("-")  # Read prompt from stdin

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            stdout=subprocess.PIPE,
            stderr=None if verbose else subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            shell=use_shell,
            encoding="utf-8",
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Codex timed out after {timeout}s")
    except FileNotFoundError:
        print("Error: 'codex' command not found. Install with: npm i -g @openai/codex", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: python review_section.py <section-file> [review-type]", file=sys.stderr)
        sys.exit(1)

    section_path = Path(sys.argv[1])
    review_type = sys.argv[2] if len(sys.argv) > 2 else "architecture"
    timeout = int(os.environ.get("CODEX_REVIEW_TIMEOUT", "120"))
    verbose = os.environ.get("CODEX_REVIEW_VERBOSE", "0") == "1"
    model = os.environ.get("CODEX_REVIEW_MODEL")

    if not section_path.is_file():
        print(f"Error: Section file not found: {section_path}", file=sys.stderr)
        sys.exit(1)

    # Locate prompt file
    script_dir = Path(__file__).resolve().parent
    prompt_path = script_dir.parent / "prompts" / f"{review_type}.md"
    if not prompt_path.is_file():
        available = [p.stem for p in (script_dir.parent / "prompts").glob("*.md") if p.stem != "holistic"]
        print(f"Error: Unknown review type '{review_type}'. Available: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    # Locate feedback directory
    # Expected structure: .codex-review/sections/<file> -> .codex-review/feedback/pass1/
    section_dir = section_path.parent
    review_dir = section_dir.parent
    feedback_dir = review_dir / "feedback" / "pass1"
    feedback_dir.mkdir(parents=True, exist_ok=True)

    section_basename = section_path.stem
    feedback_path = feedback_dir / f"{section_basename}-review.md"

    # Build prompt
    review_prompt = prompt_path.read_text(encoding="utf-8")
    section_content = section_path.read_text(encoding="utf-8")

    full_prompt = f"""{review_prompt}

---

## Document Section to Review

{section_content}"""

    print(f"Reviewing: {section_basename} (type: {review_type})...", file=sys.stderr)

    try:
        result = run_codex(full_prompt, timeout=timeout, model=model, verbose=verbose)
    except TimeoutError as e:
        print(str(e), file=sys.stderr)
        feedback_path.write_text(
            f"# Review: {section_basename}\n\n"
            f"**⚠️ TIMEOUT** — Codex did not complete within {timeout}s. "
            f"Consider increasing CODEX_REVIEW_TIMEOUT or splitting this section further.\n",
            encoding="utf-8",
        )
        sys.exit(1)

    # Write feedback
    now = datetime.now(timezone.utc).isoformat()
    feedback = f"""# Section Review: {section_basename}
**Review type**: {review_type}
**Date**: {now}

{result}
"""
    feedback_path.write_text(feedback, encoding="utf-8")
    print(f"✓ Feedback written to: {feedback_path}", file=sys.stderr)


if __name__ == "__main__":
    main()