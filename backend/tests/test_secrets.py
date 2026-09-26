"""The API key must never reach git: every file git would commit is scanned."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PATTERN = re.compile(rb"sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def committable_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPO, capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        pytest.skip(f"git unavailable: {e}")
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def test_env_file_is_ignored():
    files = committable_files()
    assert ".env" not in files
    assert not [f for f in files if re.search(r"(^|/)\.env($|\.)", f) and not f.endswith(".env.example")]


def test_no_secret_patterns_in_committable_files():
    offenders = []
    for rel in committable_files():
        path = REPO / rel
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        if PATTERN.search(path.read_bytes()):
            offenders.append(rel)
    assert offenders == [], f"possible secrets in: {offenders}"
