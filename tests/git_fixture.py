"""Disposable real-Git fixtures; immutable original metadata, no host Git configuration."""

import sys

sys.dont_write_bytecode = True

import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess

from tests.helper_support import SCRIPTS, fixture, helper, original


source = helper("source_version")
policy = helper("native_policy")


class GitFixture:
    def __init__(self, test):
        self.root = fixture(test)
        self.env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
        for key in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX", "GIT_INDEX_FILE",
                    "GIT_DIR", "GIT_WORK_TREE", "GIT_CONFIG_COUNT"):
            self.env.pop(key, None)
        for path in source.SOURCE_PATHS:
            data = original(path)
            if path == source.PROJECT:
                data = data.replace(b"CURRENT_PROJECT_VERSION = 2.1.0;", b"CURRENT_PROJECT_VERSION = 2.1.6;")
            elif path == source.LOCALIZED:
                data = data.replace(b"2.1.1", b"2.1.6")
            self.write(path, data)
        for name in ("manifest.json", "constants.xlf"):
            self.write(name, original(name))
        for path in SCRIPTS.glob("*.py"):
            self.write(Path(".github/scripts") / path.name, path.read_bytes())
        for path in (SCRIPTS.parent / "workflows").glob("*.yml"):
            self.write(Path(".github/workflows") / path.name, path.read_bytes())
        for directory in ("hooks", "migration-hooks"):
            hooks = SCRIPTS.parent / directory
            if hooks.exists():
                for path in hooks.iterdir():
                    copied = self.write(Path(".github") / directory / path.name, path.read_bytes())
                    copied.chmod(path.stat().st_mode & 0o777)
        self.write(".gitignore", b"ignored/\n")
        for path in policy.PACKAGE_LEAVES:
            self.write(path, b"selected fixture leaf " + path.encode())
        for dest, src in policy.COPIED_RESOURCES.items():
            self.write(dest, (self.root / src).read_bytes())
        self.compile_metadata()
        self.git("init", "--quiet", "--initial-branch=master")
        self.git("add", ".")
        self.git("-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "fixture")
        self.sha = self.git("rev-parse", "HEAD").decode().strip()

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, env=self.env, stderr=subprocess.PIPE)

    def cli(self, helper_name, *args):
        return subprocess.run(
            [sys.executable, str(self.root / ".github/scripts" / (helper_name + ".py")), *map(str, args)],
            cwd=self.root, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def compile_metadata(self):
        self.write(policy.BUILT_PLIST, plistlib.dumps(
            dict(source.load_plist((self.root / source.PLIST).read_bytes())),
            fmt=plistlib.FMT_BINARY,
        ))
        fields = source.localized_fields(source.decode((self.root / source.LOCALIZED).read_bytes())[0])
        self.write(policy.BUILT_ENGLISH, plistlib.dumps(
            {key: value[0] for key, value in fields.items()}, fmt=plistlib.FMT_BINARY,
        ))

    def generated(self):
        self.compile_metadata()
        self.write(policy.EXECUTABLE, b"new universal binary")
        self.write(policy.SIGNATURE, b"new signature")

    def snapshot(self):
        result = {}
        def visit(path):
            relative = path.relative_to(self.root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                result[relative] = ("link", os.readlink(path), mode)
            elif stat.S_ISREG(mode):
                try:
                    # Measurement only: see all fixture bytes even under a deliberate
                    # access-negative; restore the physical fault before any CLI runs.
                    path.chmod(stat.S_IMODE(mode) | 0o400)
                    result[relative] = ("file", path.read_bytes(), mode)
                finally:
                    path.chmod(stat.S_IMODE(mode))
            elif stat.S_ISDIR(mode):
                result[relative] = ("directory", mode)
                try:
                    path.chmod(stat.S_IMODE(mode) | 0o500)
                    for child in sorted(path.iterdir()):
                        visit(child)
                finally:
                    path.chmod(stat.S_IMODE(mode))
            else:
                result[relative] = ("special", mode)
        for path in sorted(self.root.iterdir()):
            if path.name != ".git":
                visit(path)
        return result

    def restore_selected(self):
        for path in policy.GENERATED_LEAVES:
            target = self.root / path
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)
            self.write(path, self.git("show", f"HEAD:{path}"))
