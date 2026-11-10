"""Supported owner migration push: independent hook checks before any actual push."""

import sys

sys.dont_write_bytecode = True

import argparse
import os
from pathlib import Path
import subprocess

import guards
import migration_guard
import repository


def remote_ref(ref):
    return repository.run("git", "ls-remote", "--refs", "origin", ref)


def push(old, new, ref):
    migration_guard.commit_ready(old, new, ref)
    expected = "" if old == "0" * 40 else f"{old}\t{ref}"
    if remote_ref(ref) != expected:
        raise ValueError("Migration branch advertisement differs from exact old snapshot")
    guards.require_guard(guards.MIGRATION_HOOK)
    result = repository.run(
        "git", "-c", f"core.hooksPath={Path(guards.MIGRATION_HOOK).parent.absolute()}",
        "-c", "push.followTags=false", "push", "--porcelain", "--no-follow-tags",
        "origin", f"{new}:{ref}",
        env={**os.environ, "MIGRATION_EXPECTED_OLD_SHA": old,
             "MIGRATION_NEW_SHA": new, "MIGRATION_EXPECTED_REF": ref},
    )
    updates = [line.split("\t") for line in result.splitlines()
               if line.startswith((" \t", "*\t"))]
    if len(updates) != 1 or updates[0][1] != f"{new}:{ref}":
        raise ValueError("Migration push did not perform exactly one actual branch update")
    if remote_ref(ref) != f"{new}\t{ref}":
        raise ValueError("Migration branch differs from pushed SHA")
    print(f"Guarded migration branch updated: {ref} {new}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()
    try:
        push(args.old, args.new, args.ref)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Migration push stopped: {error}. Inspect retained state; no rollback/retry.\n")
