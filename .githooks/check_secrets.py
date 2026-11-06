"""Refuse a commit that adds a credential. Run by .githooks/pre-commit.

THIS REPOSITORY IS PUBLIC. On 2026-11-05 a Neon owner password was found in
.claude/settings.json, committed since the initial commit: approving a command that had a
connection string typed into it saved the string into that tracked file. See the Secrets
section of the root CLAUDE.md.

Checks only the lines this commit ADDS, so it never blocks on history it cannot change.
A match is reported with the value cut short, never printed whole.

A real false positive is fixed by narrowing the pattern here -- never by committing with
--no-verify.

    python .githooks/check_secrets.py            # what the hook runs (staged changes)
    python .githooks/check_secrets.py FILE ...   # check whole files, e.g. before a push
"""
from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = {
    # a URL carrying a user and a password before the host -- the shape of the 2026-11-05 leak
    "connection string with a password": re.compile(
        r"[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:[^\s@'\"/]{6,}@"),
    "Neon password": re.compile(r"\bnpg_[A-Za-z0-9]{8,}"),
    "Pinecone key": re.compile(r"\bpcsk_[A-Za-z0-9_]{20,}"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    # (?<![A-Za-z0-9]) so "ask-naren-answers..." is not read as an sk- key
    "OpenAI/Anthropic-style key": re.compile(r"(?<![A-Za-z0-9])sk-(?:ant-)?[A-Za-z0-9_\-]{20,}"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{30,}"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # NAME_KEY = "long literal" -- an assignment, not a lookup like os.environ["X_KEY"]
    "hard-coded key/token/password": re.compile(
        r"\b[A-Z0-9_]*(?:API_KEY|_KEY|TOKEN|SECRET|PASSWORD)\s*[:=]\s*['\"]?[A-Za-z0-9_\-+/]{20,}['\"]?\s*$"),
}

# Env files hold secrets by design and are git-ignored; the example template is the exception.
ENV_FILE = re.compile(r"(^|/)\.env(\.[^/]*)?$")
ENV_EXAMPLE = re.compile(r"(^|/)\.env\.example$")


def _short(value: str) -> str:
    return value[:6] + "..."


def _scan(path: str, numbered_lines) -> list[str]:
    found = []
    for number, line in numbered_lines:
        for name, pattern in PATTERNS.items():
            match = pattern.search(line)
            if match:
                found.append(f"  {path}:{number}  {name}: {_short(match.group(0))}")
    return found


def staged_findings() -> list[str]:
    names = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
                           capture_output=True, text=True, check=True).stdout.split("\n")
    found = [f"  {n}  is an env file -- these hold secrets and must stay git-ignored"
             for n in names if n and ENV_FILE.search(n) and not ENV_EXAMPLE.search(n)]
    diff = subprocess.run(["git", "diff", "--cached", "-U0", "--no-color", "--no-ext-diff"],
                          capture_output=True, check=True).stdout.decode("utf-8", "replace")
    path, number, added = None, 0, {}
    for line in diff.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            number = int(re.search(r"\+(\d+)", line).group(1))
        elif path and line.startswith("+"):
            added.setdefault(path, []).append((number, line[1:]))
            number += 1
    for p, lines in added.items():
        found += _scan(p, lines)
    return found


def file_findings(paths: list[str]) -> list[str]:
    found = []
    for p in paths:
        with open(p, encoding="utf-8", errors="replace") as handle:
            found += _scan(p, enumerate(handle.read().splitlines(), 1))
    return found


def main() -> int:
    found = file_findings(sys.argv[1:]) if len(sys.argv) > 1 else staged_findings()
    if not found:
        return 0
    print("\nBLOCKED: this would put a credential in a PUBLIC repository.\n", file=sys.stderr)
    print("\n".join(found), file=sys.stderr)
    print("\nKeep secrets in Brain/.env or frontend/.env.local and read them from there.\n"
          "If one was ever committed: rotate it first, then remove it. A real false\n"
          "positive is fixed by narrowing the pattern in .githooks/check_secrets.py,\n"
          "never with --no-verify.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
