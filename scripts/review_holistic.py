#!/usr/bin/env python3
"""Invoke Codex for a full-document holistic review (pass 2).

Usage: python3 review_holistic.py <plan-file> [pass1-feedback-dir]

If pass1-feedback-dir is provided, the holistic review includes pass 1 findings
so Codex can verify they were addressed.
"""

import sys
import subprocess
import os
from pathlib import Path
from datetime import datetime, timezone


def find_codex() -> str:
    """Find the codex executable, handling Windows npm quirks."""
    import shutil

    codex_path = shutil.which("codex")
    if codex_path:
        return codex_path

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
        print("Usage: python3 review_holistic.py <plan-file> [pass1-feedback-dir]", file=sys.stderr)
        sys.exit(1)

    plan_path = Path(sys.argv[1])
    pass1_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    timeout = int(os.environ.get("CODEX_REVIEW_TIMEOUT", "180"))  # Longer default
    verbose = os.environ.get("CODEX_REVIEW_VERBOSE", "0") == "1"
    model = os.environ.get("CODEX_REVIEW_MODEL")

    if not plan_path.is_file():
        print(f"Error: Plan file not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    # Setup output directory
    review_dir = plan_path.parent / ".codex-review"
    feedback_dir = review_dir / "feedback" / "pass2"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = feedback_dir / "holistic-review.md"

    # Load holistic prompt
    script_dir = Path(__file__).resolve().parent
    holistic_prompt = (script_dir.parent / "prompts" / "holistic.md").read_text(encoding="utf-8")

    plan_content = plan_path.read_text(encoding="utf-8")

    # Collect pass 1 feedback if available
    pass1_summary = ""
    if pass1_dir and pass1_dir.is_dir():
        pass1_summary = (
            "## Previous Review Findings (Pass 1)\n\n"
            "The following issues were identified in a section-by-section review. "
            "Verify whether these have been addressed in the current version of the document. "
            "Flag any that remain unresolved.\n\n"
        )
        for f in sorted(pass1_dir.glob("*-review.md")):
            pass1_summary += f.read_text(encoding="utf-8") + "\n\n---\n\n"

    full_prompt = f"""{holistic_prompt}

{pass1_summary}

---

## Full Document to Review

{plan_content}"""

    print(f"Running holistic review on: {plan_path.name}...", file=sys.stderr)

    try:
        result = run_codex(full_prompt, timeout=timeout, model=model, verbose=verbose)
    except TimeoutError as e:
        print(str(e), file=sys.stderr)
        feedback_path.write_text(
            "# Holistic Review\n\n"
            f"**⚠️ TIMEOUT** — Codex did not complete within {timeout}s. "
            "The document may be too large for a single holistic pass. "
            "Consider increasing CODEX_REVIEW_TIMEOUT.\n",
            encoding="utf-8",
        )
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    has_pass1 = "yes" if pass1_dir and pass1_dir.is_dir() else "no"
    feedback = f"""# Holistic Review
**Date**: {now}
**Document**: {plan_path.name}
**Pass 1 feedback included**: {has_pass1}

{result}
"""
    feedback_path.write_text(feedback, encoding="utf-8")
    print(f"✓ Holistic feedback written to: {feedback_path}", file=sys.stderr)


if __name__ == "__main__":
    main()