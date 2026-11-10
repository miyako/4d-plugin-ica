import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from tests.git_fixture import GitFixture
from tests.helper_support import INTAKE, ROOT
from tests.migration_git_wrapper import HOOK, tamper_hook


ENDING = b"Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>"


class MigrationPushTests(unittest.TestCase):
    def setUp(self):
        self.fixture = GitFixture(self)
        self.root = self.fixture.root
        self.real_git = shutil.which("git")
        self.fixture.git("fetch", "--quiet", "--depth=1", "--no-tags", str(ROOT), INTAKE)
        self.tree = self.fixture.git("write-tree").decode().strip()
        self.new = self.child(INTAKE)
        self.fixture.git("update-ref", "HEAD", self.new)
        self.bare = self.root / ".git/migration-bare.git"
        self.fixture.git("init", "--quiet", "--bare", str(self.bare))
        self.fixture.git("--git-dir", str(self.bare), "fetch", "--quiet", "--depth=1", "--no-tags", str(ROOT), INTAKE)
        self.fixture.git("remote", "add", "origin", str(self.bare))
        wrapper = self.root / ".git/fixture-bin/git"
        wrapper.parent.mkdir()
        wrapper.write_bytes(("#!" + sys.executable + "\n").encode() +
                            (Path(__file__).parent / "migration_git_wrapper.py").read_bytes())
        wrapper.chmod(0o755)
        self.fixture.env.update(
            PATH=str(wrapper.parent) + os.pathsep + os.environ["PATH"],
            FIXTURE_REAL_GIT=self.real_git, FIXTURE_ROOT=str(self.root),
            FIXTURE_MIGRATION_TAMPER="none",
        )
        self.ref = "refs/heads/offline-migration"
        self.hook = self.root / HOOK
        self.original = self.hook.read_bytes()

    def child(self, parent, tree=None):
        return subprocess.check_output(
            [self.real_git, "-c", "commit.gpgSign=false", "commit-tree", tree or self.tree, "-p", parent],
            input=b"owner migration fixture, not a Bump\n\n" + ENDING + b"\n",
            cwd=self.root, env=self.fixture.env,
        ).decode().strip()

    def call(self, old="0"*40):
        return self.fixture.cli("migration_push", "--old", old, "--new", self.new, "--ref", self.ref)

    def events(self):
        path = self.root / ".git/migration-events"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def clear_events(self):
        path = self.root / ".git/migration-events"
        if path.exists():
            path.unlink()

    def remote(self):
        return self.fixture.git("--git-dir", str(self.bare), "for-each-ref", "--format=%(objectname)", self.ref).decode().strip()

    def positive(self, old="0"*40):
        self.clear_events()
        before, index = self.fixture.snapshot(), self.fixture.git("ls-files", "--stage", "-z")
        result = self.call(old)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.fixture.git("ls-files", "--stage", "-z"), index)
        self.assertEqual(self.remote(), self.new)
        self.assertEqual([event["kind"] for event in self.events()], ["remote-read", "push", "remote-read"])
        argv = self.events()[1]["argv"]
        self.assertIn("push.followTags=false", argv)
        self.assertIn("--no-follow-tags", argv)
        self.assertIn(f"core.hooksPath={self.root / '.github/migration-hooks'}", argv)
        self.assertIn(f"{self.new}:{self.ref}", argv)
        self.assertNotIn("--force", argv)
        self.assertNotIn("-f", argv)
        self.assertFalse(any(arg.startswith("+") for arg in argv))
        self.assertEqual(self.fixture.git("--git-dir", str(self.bare), "tag", "--list"), b"")
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", self.fixture.env)
        self.assertFalse(list(self.root.rglob("__pycache__")))

    def reset_fixture_remote(self):
        # Disposable fixture boundary only; the supported production wrapper never deletes or retries.
        self.fixture.git("--git-dir", str(self.bare), "update-ref", "-d", self.ref)
        self.clear_events()

    def restore_hook(self):
        if self.hook.is_symlink():
            self.hook.unlink()
        self.hook.write_bytes(self.original)
        self.hook.chmod(0o755)

    def test_initial_four_physical_hook_failures_zero_actual_push_each_restored_positive(self):
        for kind in ("missing", "nonexec", "exit0", "samebytes-symlink"):
            with self.subTest(kind=kind):
                tamper_hook(self.root, kind)
                before, index = self.fixture.snapshot(), self.fixture.git("ls-files", "--stage", "-z")
                result = self.call()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"guard", result.stderr)
                self.assertEqual(self.events(), [])
                self.assertEqual(self.remote(), "")
                self.assertEqual(self.fixture.snapshot(), before)
                self.assertEqual(self.fixture.git("ls-files", "--stage", "-z"), index)
                self.restore_hook()
                self.positive()
                self.reset_fixture_remote()

    def test_after_actual_read_four_hook_swaps_zero_push_each_restored_positive(self):
        for kind in ("missing", "nonexec", "exit0", "samebytes-symlink"):
            with self.subTest(kind=kind):
                before, index = self.fixture.snapshot(), self.fixture.git("ls-files", "--stage", "-z")
                self.fixture.env["FIXTURE_MIGRATION_TAMPER"] = kind
                marker = self.root / ".git/migration-tampered"
                if marker.exists():
                    marker.unlink()
                result = self.call()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"guard", result.stderr)
                self.assertEqual([event["kind"] for event in self.events()], ["remote-read"])
                self.assertEqual(self.events()[0]["returncode"], 0)
                self.assertEqual(self.events()[0]["stdout"], "")
                self.assertEqual(marker.read_text(), kind)
                self.assertEqual(self.remote(), "")
                self.assertEqual(self.fixture.git("ls-files", "--stage", "-z"), index)
                after = self.fixture.snapshot()
                self.assertEqual({key: value for key, value in after.items() if key != HOOK},
                                 {key: value for key, value in before.items() if key != HOOK})
                self.restore_hook()
                self.assertEqual(self.fixture.snapshot(), before)
                self.fixture.env["FIXTURE_MIGRATION_TAMPER"] = "none"
                self.positive()
                self.reset_fixture_remote()

    def test_committed_missing_and_nonexec_zero_push_then_same_fixture_positive(self):
        good = self.new
        for kind in ("missing", "nonexec"):
            with self.subTest(committed=kind):
                if kind == "missing":
                    self.fixture.git("update-index", "--force-remove", "--", HOOK)
                else:
                    oid = self.fixture.git("rev-parse", f"{good}:{HOOK}").decode().strip()
                    self.fixture.git("update-index", "--cacheinfo", f"100644,{oid},{HOOK}")
                tree = self.fixture.git("write-tree").decode().strip()
                self.new = self.child(INTAKE, tree)
                self.fixture.git("update-ref", "HEAD", self.new)
                before = self.fixture.snapshot()
                result = self.call()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"guard", result.stderr)
                self.assertEqual(self.events(), [])
                self.assertEqual(self.remote(), "")
                self.assertEqual(self.fixture.snapshot(), before)
                self.fixture.git("read-tree", good)
                self.fixture.git("update-ref", "HEAD", good)
                self.new = good
                self.positive()
                self.reset_fixture_remote()

    def test_supported_wrapper_createzero_then_exact_old_correction(self):
        self.positive()
        first = self.new
        self.new = self.child(first)
        self.fixture.git("update-ref", "HEAD", self.new)
        self.positive(first)

    def test_existing_branch_fails_exact_zero_old_snapshot_without_actual_push(self):
        self.fixture.git("--git-dir", str(self.bare), "update-ref", self.ref, INTAKE)
        before = self.fixture.snapshot()
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"exact old snapshot", result.stderr)
        self.assertEqual([event["kind"] for event in self.events()], ["remote-read"])
        self.assertEqual(self.remote(), INTAKE)
        self.assertEqual(self.fixture.snapshot(), before)
        self.reset_fixture_remote()
        self.positive()
