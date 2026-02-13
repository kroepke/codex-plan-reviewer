#!/usr/bin/env python3
"""Iteratively review and refine a single section using Codex session resume.

Usage: python iterate_section.py <section-file> <revised-section-file> [review-type] [max-rounds]

Interactive mode (default): pauses between rounds for you to edit the revised file.
Non-interactive mode (--no-interactive): runs all rounds without pausing, expects
  the revised file to be updated externally (e.g., by Claude Code) between invocations.

Single-round mode (--round N): runs only round N. Useful when Claude Code drives
  the loop and handles revisions between invocations.
"""

import sys
import subprocess
import os
import re
import shutil
import argparse
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


def run_codex(
    prompt: str,
    timeout: int,
    model: str | None = None,
    verbose: bool = False,
    resume: bool = False,
) -> str:
    """Run codex exec (or resume), piping the prompt via stdin."""
    codex_bin = find_codex()
    use_shell = sys.platform == "win32" and not codex_bin

    if codex_bin:
        cmd = [codex_bin, "exec"]
    else:
        cmd = ["codex", "exec"]

    if resume:
        cmd.extend(["resume", "--last"])
    else:
        cmd.append("--ephemeral")

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
            timeout=timeout,
            shell=use_shell,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"Codex timed out after {timeout}s")
    except FileNotFoundError:
        print("Error: 'codex' command not found. Install with: npm i -g @openai/codex", file=sys.stderr)
        sys.exit(1)


def count_issues(text: str) -> int:
    """Count critical and warning findings."""
    return len(re.findall(r"🔴|🟡", text))


def main():
    parser = argparse.ArgumentParser(description="Iterative section review with Codex resume")
    parser.add_argument("section_file", help="Original section file")
    parser.add_argument("revised_file", help="File that gets revised between rounds")
    parser.add_argument("review_type", nargs="?", default="architecture",
                        help="Review type: architecture, implementation, api, data")
    parser.add_argument("max_rounds", nargs="?", type=int, default=3,
                        help="Maximum review rounds (default: 3)")
    parser.add_argument("--no-interactive", action="store_true",
                        help="Don't pause between rounds")
    parser.add_argument("--round", type=int, dest="single_round",
                        help="Run only this round number (for external loop control)")
    args = parser.parse_args()

    section_path = Path(args.section_file)
    revised_path = Path(args.revised_file)
    review_type = args.review_type
    max_rounds = args.max_rounds
    interactive = not args.no_interactive
    timeout = int(os.environ.get("CODEX_REVIEW_TIMEOUT", "120"))
    verbose = os.environ.get("CODEX_REVIEW_VERBOSE", "0") == "1"
    model = os.environ.get("CODEX_REVIEW_MODEL")

    if not section_path.is_file():
        print(f"Error: Section file not found: {section_path}", file=sys.stderr)
        sys.exit(1)

    # Locate prompt
    script_dir = Path(__file__).resolve().parent
    prompt_path = script_dir.parent / "prompts" / f"{review_type}.md"
    if not prompt_path.is_file():
        available = [p.stem for p in (script_dir.parent / "prompts").glob("*.md") if p.stem != "holistic"]
        print(f"Error: Unknown review type '{review_type}'. Available: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    # Setup iteration directory
    section_basename = section_path.stem
    section_dir = section_path.parent
    review_dir = section_dir.parent
    iteration_dir = review_dir / "feedback" / "iterations" / section_basename

    # Only clean on round 1 (or full run)
    if args.single_round is None or args.single_round == 1:
        if iteration_dir.exists():
            shutil.rmtree(iteration_dir)
    iteration_dir.mkdir(parents=True, exist_ok=True)

    review_prompt = prompt_path.read_text(encoding="utf-8")

    # --- Determine which rounds to run ---
    if args.single_round is not None:
        rounds_to_run = [args.single_round]
    else:
        rounds_to_run = list(range(1, max_rounds + 1))

    prev_issues = 0
    last_result = ""

    for round_num in rounds_to_run:
        round_file = iteration_dir / f"round-{round_num:02d}.md"

        if round_num == 1:
            # --- Round 1: Initial review ---
            print(f"=== Round 1/{max_rounds}: Initial review of {section_basename} ===", file=sys.stderr)

            section_content = section_path.read_text(encoding="utf-8")
            full_prompt = f"""{review_prompt}

---

## Document Section to Review

{section_content}

---

After your review, I will revise the section and show you the updated version. You will then evaluate whether your concerns were addressed. We may go through multiple rounds of this."""

            try:
                result = run_codex(full_prompt, timeout=timeout, model=model, verbose=verbose, resume=False)
            except TimeoutError as e:
                print(str(e), file=sys.stderr)
                sys.exit(1)

            now = datetime.now(timezone.utc).isoformat()
            round_file.write_text(
                f"# Iteration Round 1: Initial Review\n"
                f"**Section**: {section_basename}\n"
                f"**Review type**: {review_type}\n"
                f"**Date**: {now}\n\n"
                f"{result}\n",
                encoding="utf-8",
            )

            prev_issues = count_issues(result)
            last_result = result
            print(f"✓ Round 1 feedback: {round_file}", file=sys.stderr)
            print(f"  Issues found: {prev_issues}", file=sys.stderr)

        else:
            # --- Subsequent rounds: resume with revised content ---
            if interactive:
                print(f"\n--- Edit the file: {revised_path} ---", file=sys.stderr)
                print("Press ENTER when done (or type 'q' to stop): ", file=sys.stderr, end="", flush=True)
                try:
                    user_input = input()
                except EOFError:
                    user_input = "q"

                if user_input.strip().lower() in ("q", "quit"):
                    print(f"Stopped by user after round {round_num - 1}.", file=sys.stderr)
                    break

            if not revised_path.is_file():
                print(f"Error: Revised file not found: {revised_path}", file=sys.stderr)
                sys.exit(1)

            revised_content = revised_path.read_text(encoding="utf-8")

            print(f"=== Round {round_num}/{max_rounds}: Re-review after revision ===", file=sys.stderr)

            resume_prompt = f"""Here is the revised version of the section, updated based on your previous feedback.

Please evaluate:
1. Which of your previous findings have been addressed? Mark each as RESOLVED or UNRESOLVED.
2. Did the revisions introduce any NEW issues?
3. Are there any remaining critical or warning items?

Use the same severity format (🔴 🟡 🔵) for any remaining or new issues.

If all critical and warning issues are resolved, state: "✅ SECTION APPROVED — no critical or warning issues remain."

---

## Revised Section

{revised_content}"""

            try:
                result = run_codex(resume_prompt, timeout=timeout, model=model, verbose=verbose, resume=True)
            except TimeoutError as e:
                print(str(e), file=sys.stderr)
                result = ""

            # If resume failed (empty result), fall back to fresh exec
            if not result:
                print("Resume failed, falling back to fresh exec...", file=sys.stderr)
                try:
                    result = run_codex(resume_prompt, timeout=timeout, model=model, verbose=verbose, resume=False)
                except TimeoutError:
                    print(f"Error: Fresh exec also timed out on round {round_num}.", file=sys.stderr)
                    sys.exit(1)

            now = datetime.now(timezone.utc).isoformat()
            round_file.write_text(
                f"# Iteration Round {round_num}\n"
                f"**Date**: {now}\n\n"
                f"{result}\n",
                encoding="utf-8",
            )

            current_issues = count_issues(result)
            last_result = result
            print(f"✓ Round {round_num} feedback: {round_file}", file=sys.stderr)
            print(f"  Issues: {current_issues} (was: {prev_issues})", file=sys.stderr)

            # Check for approval
            if "SECTION APPROVED" in result:
                print(f"\n🎉 Section approved by Codex after {round_num} rounds!", file=sys.stderr)
                break

            # Convergence warning
            if current_issues >= prev_issues and round_num >= 3:
                print(
                    f"\n⚠️  Issues not decreasing ({current_issues} >= {prev_issues}). "
                    "Consider manual review.", file=sys.stderr,
                )

            prev_issues = current_issues

    # --- Write summary ---
    summary_lines = [
        f"# Iteration Summary: {section_basename}\n",
        f"- **Review type**: {review_type}",
        f"- **Approved**: {'yes' if 'SECTION APPROVED' in last_result else 'no'}",
        "",
        "## Round History",
    ]
    for f in sorted(iteration_dir.glob("round-*.md")):
        text = f.read_text(encoding="utf-8")
        issues = count_issues(text)
        summary_lines.append(f"- {f.name}: {issues} issues")

    (iteration_dir / "summary.md").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

    print(f"\nIteration feedback: {iteration_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()