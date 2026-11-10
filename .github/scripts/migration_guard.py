"""Owner-invoked single-ref migration guard; does not itself push or publish."""

import sys

sys.dont_write_bytecode = True

import os
import subprocess

import guards
import repository
import source_version


def commit_ready(old, new, ref):
    guards.require_guard(guards.MIGRATION_HOOK)
    guards.sha(old)
    guards.sha(new)
    guards.branch(ref)
    repository.verify_checkout(new)
    parent = guards.INTAKE if old == "0" * 40 else old
    guards.direct_child(parent, new)
    repository.run("git", "merge-base", "--is-ancestor", guards.INTAKE, new)
    source_version.read()


def guard(updates):
    guards.require_guard(guards.MIGRATION_HOOK)
    old, new, ref = (os.environ[key] for key in (
        "MIGRATION_EXPECTED_OLD_SHA", "MIGRATION_NEW_SHA", "MIGRATION_EXPECTED_REF",
    ))
    guards.advertisement(updates, old, new, ref)
    commit_ready(old, new, ref)


if __name__ == "__main__":
    try:
        guard(sys.stdin.read())
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f"Migration push rejected: {error}", file=sys.stderr)
        sys.exit(1)
