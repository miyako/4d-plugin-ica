#!/usr/bin/env python3
"""Fixture-only real-Git wrapper: mutate advertisements, never production repositories."""

import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import subprocess


real = os.environ["FIXTURE_REAL_GIT"]
root = Path(os.environ["FIXTURE_ROOT"])
assert root.name.startswith(".ica-offline-")
bare = root / ".git/offline-remote.git"
args = sys.argv[1:]
if "push" in args:
    with (root / ".git/push-calls").open("a") as stream:
        stream.write(json.dumps(args) + "\n")
if args and args[0] == "ls-remote":
    counter = root / ".git/remote-reads"
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    result = subprocess.run([real, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode == 0 and count == 2:
        mode = os.environ.get("FIXTURE_RACE", "none")
        hook = root / ".github/hooks/pre-push"
        if mode == "late-exit0":
            hook.write_bytes(b"#!/bin/sh\nexit 0\n")
            hook.chmod(0o755)
        elif mode == "late-symlink":
            backup = root / ".git/original-hook"
            backup.write_bytes(hook.read_bytes())
            backup.chmod(0o755)
            hook.unlink()
            hook.symlink_to(backup)
        elif mode != "none":
            command = [real, "--git-dir", str(bare)]
            if mode == "delete":
                subprocess.run([*command, "update-ref", "-d", "refs/heads/master"], check=True)
                advertised = "DELETED"
            else:
                if mode == "same-result":
                    advertised = subprocess.check_output([real, "rev-parse", "HEAD"]).decode().strip()
                    subprocess.run([*command, "fetch", "--quiet", "--no-tags", str(root), advertised], check=True)
                elif mode in ("advance", "rewind"):
                    advertised = os.environ["FIXTURE_RACE_SHA"]
                else:
                    raise ValueError(mode)
                subprocess.run([*command, "update-ref", "refs/heads/master", advertised], check=True)
            (root / ".git/raced-remote").write_text(advertised)
    sys.stdout.buffer.write(result.stdout)
    sys.stderr.buffer.write(result.stderr)
    sys.exit(result.returncode)
os.execv(real, [real, *args])
