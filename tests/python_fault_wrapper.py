"""Fixture-only interpreter wrapper: inject one OS error into the real extracted CLI."""

import sys

sys.dont_write_bytecode = True

import errno
import os
from pathlib import Path
import runpy


root = Path.cwd()
assert root.name.startswith(".ica-offline-")
assert (sys.argv[1], sys.argv[2]) in (
    (".github/scripts/native.py", "cleanup"), (".github/scripts/publication.py", "check"),
)
assert "-B" not in sys.argv
assert "PYTHONDONTWRITEBYTECODE" not in os.environ
target = root / os.environ["FIXTURE_FAULT_PATH"]
original_lstat = os.lstat
original_stat = os.stat
original_access = os.access
kind = os.environ["FIXTURE_FAULT_KIND"]


def lstat(path, *args, **kwargs):
    if Path(path).absolute() == target and kind in ("EACCES", "EIO", "ENOTDIR"):
        raise OSError(getattr(errno, kind), "fixture-only OS fault", str(path))
    return original_lstat(path, *args, **kwargs)


def stat(path, *args, **kwargs):
    if kwargs.get("follow_symlinks") is False:
        return lstat(path, *args)
    return original_stat(path, *args, **kwargs)


def access(path, mode, *args, **kwargs):
    if Path(path).absolute() == target and kind == "access-false":
        return False
    return original_access(path, mode, *args, **kwargs)


os.lstat = lstat
os.stat = stat
os.access = access
sys.argv = sys.argv[1:]
sys.path.insert(0, str(root / ".github/scripts"))
runpy.run_path(sys.argv[0], run_name="__main__")
