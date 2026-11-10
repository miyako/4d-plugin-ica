#!/usr/bin/env python3
"""Fixture-only interception after a real read-only migration branch advertisement."""

import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import subprocess


HOOK = ".github/migration-hooks/pre-push"


def tamper_hook(root, kind):
    hook = root / HOOK
    if kind == "missing":
        hook.unlink()
    elif kind == "nonexec":
        hook.chmod(0o644)
    elif kind == "exit0":
        hook.write_bytes(b"#!/bin/sh\nexit 0\n")
    elif kind == "samebytes-symlink":
        backup = root / ".git/migration-hook-backup"
        backup.write_bytes(hook.read_bytes())
        backup.chmod(0o755)
        hook.unlink()
        hook.symlink_to(backup)
    else:
        raise ValueError(kind)


def main():
    root = Path(os.environ["FIXTURE_ROOT"])
    assert root.name.startswith(".ica-offline-") and Path.cwd() == root
    real = os.environ["FIXTURE_REAL_GIT"]
    args = sys.argv[1:]

    def event(kind, **fields):
        with (root / ".git/migration-events").open("a") as stream:
            stream.write(json.dumps({"kind": kind, "argv": args, **fields}) + "\n")

    if args and args[0] == "ls-remote":
        result = subprocess.run([real, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        event("remote-read", returncode=result.returncode, stdout=result.stdout.decode())
        marker = root / ".git/migration-tampered"
        kind = os.environ.get("FIXTURE_MIGRATION_TAMPER", "none")
        if result.returncode == 0 and kind != "none" and not marker.exists():
            tamper_hook(root, kind)
            marker.write_text(kind)
        sys.stdout.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        sys.exit(result.returncode)
    if "push" in args:
        event("push")
    os.execv(real, [real, *args])


if __name__ == "__main__":
    main()
