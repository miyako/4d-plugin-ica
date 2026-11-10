"""Shared fail-closed physical path checks; the checkout root alone may contain .git."""

import errno
import os
from pathlib import Path
import stat


def optional_lstat(path):
    try:
        return Path(path).lstat()
    except OSError as error:
        if error.errno == errno.ENOENT:
            return None
        raise


def directory(path, *, writable=False):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"Not a regular directory: {path}")
    mask = os.R_OK | os.X_OK | (os.W_OK if writable else 0)
    if not info.st_mode & 0o444 or not info.st_mode & 0o111 \
            or (writable and not info.st_mode & 0o222) or not os.access(path, mask):
        raise ValueError(f"Inaccessible directory: {path}")
    return info


def ancestors(root, relative):
    root, relative = Path(root).absolute(), Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in (".", "..") for p in relative.parts):
        raise ValueError(f"Expected a checkout-relative path: {relative}")
    directory(root)
    current = root
    for part in relative.parts[:-1]:
        current /= part
        directory(current)
        if optional_lstat(current / ".git") is not None:
            raise ValueError(f"Nested Git marker: {current / '.git'}")
    return root / relative


def regular_file(root, relative, *, nonempty=True, writable=False):
    path = ancestors(root, relative)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Not a regular file: {path}")
    if nonempty and info.st_size == 0:
        raise ValueError(f"Empty file: {path}")
    if not info.st_mode & 0o444 or not os.access(path, os.R_OK):
        raise ValueError(f"Unreadable file: {path}")
    if writable and (not info.st_mode & 0o222 or not os.access(path, os.W_OK)):
        raise ValueError(f"Unwritable file: {path}")
    return path


def cleanup_plan(root, targets, *, allowed_file, allowed_directory=lambda path: True):
    """Validate the complete typed tree and all deletion parents before any deletion."""
    root = Path(root).absolute()
    plan = []
    seen = set()

    def visit(relative, kind):
        relative = Path(relative)
        path = ancestors(root, relative)
        info = optional_lstat(path)
        if info is None:
            return
        if relative in seen:
            raise ValueError(f"Overlapping cleanup targets: {relative}")
        seen.add(relative)
        if kind == "directory":
            directory(path)
            if not allowed_directory(relative.as_posix()):
                raise ValueError(f"Not a proven generated cleanup directory: {relative}")
            if optional_lstat(path / ".git") is not None:
                raise ValueError(f"Nested Git marker: {path / '.git'}")
            for child in sorted(path.iterdir()):
                child_info = child.lstat()
                visit(relative / child.name, "directory" if stat.S_ISDIR(child_info.st_mode) else "file")
        elif kind == "file":
            regular_file(root, relative, nonempty=False)
            if not allowed_file(relative.as_posix()):
                raise ValueError(f"Not a proven generated cleanup leaf: {relative}")
        else:
            raise ValueError(f"Unsupported cleanup target type: {kind}")
        directory(path.parent, writable=True)
        plan.append((path, kind))

    for relative, kind in targets:
        relative = Path(relative)
        if relative.is_absolute() or not relative.parts or any(p in (".", "..") for p in relative.parts):
            raise ValueError(f"Expected a checkout-relative cleanup path: {relative}")
        # A missing enclosing directory is absence only after all existing
        # ancestors have passed access and nested-marker checks.
        current = root
        missing = False
        for component in Path(relative).parts[:-1]:
            directory(current)
            current /= component
            info = optional_lstat(current)
            if info is None:
                missing = True
                break
            directory(current)
            if optional_lstat(current / ".git") is not None:
                raise ValueError(f"Nested Git marker: {current / '.git'}")
        if not missing:
            visit(relative, kind)
    return plan


def execute_cleanup(plan):
    for path, kind in plan:
        if kind == "directory":
            path.rmdir()
        else:
            path.unlink()
