"""Verify immutable selected/index/raw bytes independently of Git's stat caches."""

import sys

sys.dont_write_bytecode = True

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess

from physical import regular_file


def run(*args, input=None, env=None, cwd=None):
    result = subprocess.run(
        args, input=None if input is None else input.encode(), env=env, cwd=cwd,
        check=True, stdout=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8", "surrogateescape").rstrip("\n")


def selected_sha(sha, root=Path(".")):
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected immutable selected github.sha")
    if run("git", "rev-parse", "HEAD", cwd=root) != sha:
        raise ValueError("Checkout HEAD does not match selected SHA")


def entries(output, *, index=False):
    result = {}
    for record in filter(None, output.split("\0")):
        header, path = record.split("\t", 1)
        first, second, third = header.split()
        if index:
            mode, oid = first, second
            if third != "0":
                raise ValueError("Unmerged index")
        else:
            mode, oid = first, third
            if second != "blob":
                raise ValueError("ICA has no dependency gitlinks")
        if mode not in ("100644", "100755") or not re.fullmatch(r"[0-9a-f]{40}", oid):
            raise ValueError(f"Unsupported selected/index type: {path}")
        if path in result:
            raise ValueError(f"Duplicate selected/index path: {path}")
        result[path] = (mode, oid)
    return result


def actual_blob(path, root=Path(".")):
    path = regular_file(root, path, nonempty=False)
    data = path.read_bytes()
    mode = "100755" if path.lstat().st_mode & 0o111 else "100644"
    return mode, hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def selected_entries(sha, root=Path(".")):
    selected_sha(sha, root)
    return entries(run("git", "ls-tree", "-r", "-z", sha, "--", cwd=root))


def verify_checkout(sha, *, root=Path("."), final=False, assets=()):
    root = Path(root).absolute()
    selected = selected_entries(sha, root)
    indexed = entries(run("git", "ls-files", "--stage", "-z", "--", cwd=root), index=True)
    for flag in ("-v", "-f"):
        records = run("git", "ls-files", flag, "-z", "--", cwd=root).split("\0")
        if any(record and not record.startswith("H ") for record in records):
            raise ValueError(f"Hidden index/stat flags are unsupported ({flag})")
    if indexed != selected:
        raise ValueError("Index differs from immutable selected tree")
    if final:
        from native_policy import GENERATED_LEAVES, generated_file
    for path, expected in selected.items():
        if final and path in GENERATED_LEAVES:
            continue
        if actual_blob(path, root) != expected:
            raise ValueError(f"Raw working bytes/mode differ from selected SHA: {path}")
    untracked = filter(None, run("git", "ls-files", "--others", "-z", "--", cwd=root).split("\0"))
    for path in untracked:
        if not final or not (generated_file(path) or path in assets):
            raise ValueError(f"Untracked/ignored source or unexpected output: {path}")
        regular_file(root, path, nonempty=False)
    if not final and run("git", "status", "--porcelain", "--untracked-files=all", cwd=root):
        raise ValueError("Preflight requires a globally clean checkout")
    return selected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    try:
        verify_checkout(args.sha)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Source checkout rejected: {error}\n")
