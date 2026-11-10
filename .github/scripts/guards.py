"""Shared exact committed executable and literal-last-line commit checks."""

import sys

sys.dont_write_bytecode = True

import os
from pathlib import Path
import re
import subprocess

import repository


TRAILER = b"Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>"
BUMP_HOOK = ".github/hooks/pre-push"
MIGRATION_HOOK = ".github/migration-hooks/pre-push"
INTAKE = "2b94d2ab88113db7bd4d67365ea547cf62971e4a"


def sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Expected a literal immutable SHA")
    return value


def branch(ref):
    if not isinstance(ref, str) or not ref.startswith("refs/heads/"):
        raise ValueError("Expected one full branch ref")
    repository.run("git", "check-ref-format", ref)


def git_bytes(*args):
    return subprocess.check_output(["git", *args])


def require_guard(relative):
    path = Path(relative)
    if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("Mandatory executable nonsymlink guard is missing")
    committed = repository.entries(repository.run("git", "ls-tree", "-z", "HEAD", "--", relative))
    expected = committed.get(relative)
    if set(committed) != {relative} or expected[0] != "100755" \
            or repository.actual_blob(relative) != expected:
        raise ValueError("Mandatory guard must equal its committed100755 raw blob")


def literal_ending_trailer(commit):
    raw = git_bytes("cat-file", "commit", sha(commit))
    message = raw.split(b"\n\n", 1)[1]
    if message.endswith(b"\n"):
        message = message[:-1]
    if message.rsplit(b"\n", 1)[-1] != TRAILER:
        raise ValueError("Actual last commit-message line must EXACTLY equal the literal Copilot App trailer")


def direct_child(old, new):
    sha(old)
    sha(new)
    if new == old or repository.run("git", "rev-list", "--parents", "-n", "1", new) != f"{new} {old}":
        raise ValueError("Expected a single direct child")
    literal_ending_trailer(new)


def advertisement(updates, old, new, ref):
    sha(old)
    sha(new)
    branch(ref)
    rows = updates.splitlines()
    if len(rows) != 1 or len(rows[0].split()) != 4:
        raise ValueError("Expected exactly one advertised update, not zero or multiple")
    local_ref, local_sha, remote_ref, advertised_old = rows[0].split()
    if local_ref not in (new, "HEAD") or (local_sha, remote_ref, advertised_old) != (new, ref, old):
        raise ValueError("Literal local SHA/HEAD, local SHA, remote ref or advertised old SHA differs")
