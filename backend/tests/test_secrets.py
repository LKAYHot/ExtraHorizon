"""API keys must never reach git: every file git would commit is scanned — for key patterns
and for the actual secret values of the local (git-ignored) .env. Values are never printed."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PATTERN = re.compile(rb"sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{35}|AQ\.[A-Za-z0-9_-]{40,}|"
                     rb"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.I)


def committable_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPO, capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        pytest.skip(f"git unavailable: {e}")
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def local_secret_values() -> list[bytes]:
    values = []
    for env in (REPO / ".env", REPO / "backend" / ".env"):
        if not env.is_file():
            continue
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            name, value = line.split("=", 1)
            value = value.strip().strip("'\"")
            if SECRET_NAME.search(name) and len(value) >= 16:
                values.append(value.encode())
    return values


def test_env_file_is_ignored():
    files = committable_files()
    assert ".env" not in files
    assert not [f for f in files if re.search(r"(^|/)\.env($|\.)", f) and not f.endswith(".env.example")]


def test_no_secrets_in_committable_files():
    secrets = local_secret_values()
    offenders = []
    for rel in committable_files():
        path = REPO / rel
        if not path.is_file() or path.stat().st_size > 5_000_000:
            continue
        data = path.read_bytes()
        if PATTERN.search(data) or any(v in data for v in secrets):
            offenders.append(rel)
    assert offenders == [], f"possible secrets in: {offenders}"
