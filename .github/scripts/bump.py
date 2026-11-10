"""Create one exact source-version child and perform one guarded branch push."""

import sys

sys.dont_write_bytecode = True

import argparse
import os
from pathlib import Path
import subprocess

import guards
import repository
import source_version


run = repository.run


def require_guard():
    guards.require_guard(guards.BUMP_HOOK)


def remote_ref(ref):
    guards.branch(ref)
    lines = run("git", "ls-remote", "--refs", "origin", ref).splitlines()
    if len(lines) != 1:
        raise ValueError("Selected remote branch is missing or ambiguous")
    fields = lines[0].split()
    if len(fields) != 2 or fields[1] != ref:
        raise ValueError("Malformed remote branch advertisement")
    return guards.sha(fields[0])


def commit_ready(old, ref, new):
    require_guard()
    guards.branch(ref)
    repository.verify_checkout(new)
    guards.direct_child(old, new)
    identities = guards.git_bytes(
        "show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce", new,
    ).removesuffix(b"\n").split(b"\0")
    if identities != [
        b"github-actions[bot]", b"github-actions[bot]@users.noreply.github.com",
        b"github-actions[bot]", b"github-actions[bot]@users.noreply.github.com",
    ]:
        raise ValueError("Actual Bump author AND committer must match exact Actions bot names/emails")
    paths = set(filter(None, run(
        "git", "diff-tree", "--no-commit-id", "--name-only", "--no-renames", "-r", "-z", new,
    ).split("\0")))
    allowed = {str(path) for path in source_version.SOURCE_PATHS}
    if not paths or not paths.issubset(allowed):
        raise ValueError("Bump must be nonempty and confined to the three version source paths")
    before = {path: guards.git_bytes("show", f"{old}:{path}") for path in source_version.SOURCE_PATHS}
    current = source_version.read()
    previous = source_version.inspect_data(before)[0]
    if current not in {source_version.next_version(previous, mode) for mode in ("patch", "minor", "major")}:
        raise ValueError("Bump must be a canonical patch/minor/major increment")
    if source_version.source_data(Path(".")) != source_version.render_version(before, current):
        raise ValueError("Bump changed bytes other than exact version token spans")


def guard(updates):
    require_guard()
    old, ref, new = (os.environ[key] for key in ("BUMP_EXPECTED_SHA", "BUMP_EXPECTED_REF", "BUMP_NEW_SHA"))
    commit_ready(old, ref, new)
    guards.advertisement(updates, old, new, ref)


def bump_branch(old, ref, mode):
    require_guard()
    guards.sha(old)
    guards.branch(ref)
    repository.verify_checkout(old)
    if remote_ref(ref) != old:
        raise ValueError("Selected branch moved since dispatch")
    version = source_version.bump(mode)
    run("git", "add", "--", *map(str, source_version.SOURCE_PATHS))
    run(
        "git", "-c", "user.name=github-actions[bot]", "-c",
        "user.email=github-actions[bot]@users.noreply.github.com",
        "-c", "commit.gpgSign=false", "commit", "-m", f"chore: bump version to {version}",
        "-m", guards.TRAILER.decode(),
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "github-actions[bot]",
            "GIT_AUTHOR_EMAIL": "github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "github-actions[bot]",
            "GIT_COMMITTER_EMAIL": "github-actions[bot]@users.noreply.github.com",
        },
    )
    new = run("git", "rev-parse", "HEAD")
    commit_ready(old, ref, new)
    if remote_ref(ref) != old:
        raise ValueError("Selected branch moved during bump")
    require_guard()
    result = run(
        "git", "-c", f"core.hooksPath={Path(guards.BUMP_HOOK).parent.absolute()}",
        "-c", "push.followTags=false", "push", "--porcelain", "--no-follow-tags",
        "origin", f"{new}:{ref}",
        env={
            **os.environ, "BUMP_EXPECTED_SHA": old,
            "BUMP_EXPECTED_REF": ref, "BUMP_NEW_SHA": new,
        },
    )
    if not any(line.startswith(" \t") and line.split("\t")[1] == f"{new}:{ref}" for line in result.splitlines()):
        raise ValueError("Push did not create an actual branch update")
    if remote_ref(ref) != new:
        raise ValueError("Pushed branch differs from new SHA")
    print(f"Bumped source to {version}: {new}; run Build independently on {ref}")
    return new


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("patch", "minor", "major"))
    parser.add_argument("--sha")
    parser.add_argument("--ref")
    parser.add_argument("--guard", action="store_true")
    args = parser.parse_args(argv)
    if args.guard:
        guard(sys.stdin.read())
    elif args.mode and args.sha and args.ref:
        bump_branch(args.sha, args.ref, args.mode)
    else:
        parser.error("mode, --sha and --ref are required")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print(f"Bump stopped: {error}. Inspect retained state; no rollback/retry.", file=sys.stderr)
        sys.exit(1)
