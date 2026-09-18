"""Fail when likely credentials are tracked in the working tree or Git history."""

from __future__ import annotations

import re
import subprocess


PATTERNS = [
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"(?i)(api[_-]?key|access[_-]?token|secret)\s*[=:]\s*['\"]?[A-Za-z0-9_./+-]{16,}"),
]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def contains_secret(data: bytes) -> bool:
    return any(pattern.search(data) for pattern in PATTERNS)


def main() -> int:
    tracked = git("ls-files", "-z").split(b"\0")
    findings: list[str] = []
    for raw_path in filter(None, tracked):
        path = raw_path.decode("utf-8", errors="replace")
        try:
            data = git("show", f"HEAD:{path}")
        except subprocess.CalledProcessError:
            continue
        if contains_secret(data):
            findings.append(f"tracked file: {path}")

    commits = git("rev-list", "--all").decode().splitlines()
    for commit in commits:
        try:
            diff = git("show", "--format=", "--no-ext-diff", commit)
        except subprocess.CalledProcessError:
            continue
        if contains_secret(diff):
            findings.append(f"Git history commit: {commit[:12]}")

    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        check=False,
    ).returncode == 0
    tracked_env = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    if not ignored:
        findings.append(".env is not ignored")
    if tracked_env:
        findings.append(".env is tracked")

    if findings:
        print("Secret scan: FAIL")
        for finding in sorted(set(findings)):
            print(f"- {finding}")
        return 1
    print(f"Secret scan: PASS ({len(tracked)} tracked paths, {len(commits)} commits checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
