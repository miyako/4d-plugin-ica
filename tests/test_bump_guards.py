import sys

sys.dont_write_bytecode = True

import os
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from tests.git_fixture import GitFixture, source
from tests.helper_support import INTAKE, ROOT


EXACT = b"Co-authored-by: Copilot App <223556219+Copilot@users.noreply.github.com>"


class BumpGuardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = GitFixture(self)
        self.root = self.fixture.root
        self.old = self.fixture.sha

    def commit_tree(self, tree, parent, message, identities=None):
        return subprocess.check_output(
            ["git", "-c", "commit.gpgSign=false", "commit-tree", tree, "-p", parent],
            input=message, cwd=self.root, env={
                **self.fixture.env,
                "GIT_AUTHOR_NAME": "github-actions[bot]",
                "GIT_AUTHOR_EMAIL": "github-actions[bot]@users.noreply.github.com",
                "GIT_COMMITTER_NAME": "github-actions[bot]",
                "GIT_COMMITTER_EMAIL": "github-actions[bot]@users.noreply.github.com",
                **(identities or {}),
            },
        ).decode().strip()

    def assert_actual_bot_identities(self, commit):
        actual = self.fixture.git("show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce", commit)
        self.assertEqual(actual.removesuffix(b"\n").split(b"\0"), [
            b"github-actions[bot]", b"github-actions[bot]@users.noreply.github.com",
            b"github-actions[bot]", b"github-actions[bot]@users.noreply.github.com",
        ])

    def select(self, commit):
        self.fixture.git("update-ref", "HEAD", commit)

    def hook(self, kind, old, new, *, row=None, env=None):
        prefix = "BUMP" if kind == "bump" else "MIGRATION"
        variables = (
            {"BUMP_EXPECTED_SHA": old, "BUMP_NEW_SHA": new, "BUMP_EXPECTED_REF": "refs/heads/master"}
            if prefix == "BUMP" else
            {"MIGRATION_EXPECTED_OLD_SHA": old, "MIGRATION_NEW_SHA": new, "MIGRATION_EXPECTED_REF": "refs/heads/master"}
        )
        hook = ".github/hooks/pre-push" if kind == "bump" else ".github/migration-hooks/pre-push"
        return subprocess.run(
            [str(self.root / hook)],
            input=(row if row is not None else f"HEAD {new} refs/heads/master {old}\n").encode(),
            cwd=self.root, env={**self.fixture.env, **variables, **(env or {})},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def ready_tree(self):
        source.bump("patch", self.root)
        self.fixture.git("add", "--", *map(str, source.SOURCE_PATHS))
        return self.fixture.git("write-tree").decode().strip()

    def test_bump_actual_hook_exact_lastline_negative_then_exact_positive_each(self):
        tree = self.ready_tree()
        messages = (
            b"prefix " + EXACT,
            b" " + EXACT,
            EXACT + b" ",
            EXACT + b"\t",
            EXACT + b"\nnot the last line",
            EXACT + b"\n\n",
        )
        for last in messages:
            with self.subTest(message=last):
                bad = self.commit_tree(tree, self.old, b"fixture message\n\n" + last + b"\n")
                self.assert_actual_bot_identities(bad)
                self.select(bad)
                raw = self.fixture.git("cat-file", "commit", bad).split(b"\n\n", 1)[1]
                self.assertIn(last, raw)
                before = self.fixture.snapshot()
                result = self.hook("bump", self.old, bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"Actual last commit-message line", result.stderr)
                self.assertEqual(self.fixture.snapshot(), before)
                good = self.commit_tree(tree, self.old, b"fixture message\n\n" + EXACT + b"\n")
                self.assert_actual_bot_identities(good)
                self.select(good)
                result = self.hook("bump", self.old, good)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                message = self.fixture.git("cat-file", "commit", good).split(b"\n\n", 1)[1]
                self.assertEqual(message[:-1].rsplit(b"\n", 1)[-1], EXACT)
                self.assertEqual(self.fixture.snapshot(), before)

    def test_migration_actual_hook_exact_lastline_negative_then_exact_positive_each(self):
        self.fixture.git("fetch", "--quiet", "--depth=1", "--no-tags", str(ROOT), INTAKE)
        tree = self.fixture.git("write-tree").decode().strip()
        for last in (
            b"prefix " + EXACT, b" " + EXACT, EXACT + b" ", EXACT + b"\t",
            EXACT + b"\nnot last", EXACT + b"\n\n",
        ):
            with self.subTest(message=last):
                bad = self.commit_tree(tree, INTAKE, b"migration fixture\n\n" + last + b"\n")
                self.assert_actual_bot_identities(bad)
                self.select(bad)
                before = self.fixture.snapshot()
                result = self.hook("migration", "0" * 40, bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"Actual last commit-message line", result.stderr)
                self.assertEqual(self.fixture.snapshot(), before)
                good = self.commit_tree(tree, INTAKE, b"migration fixture\n\n" + EXACT + b"\n")
                self.assert_actual_bot_identities(good)
                self.select(good)
                result = self.hook("migration", "0" * 40, good)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(self.fixture.snapshot(), before)

    def test_bump_actual_author_and_committer_each_component_then_bot_positive(self):
        tree = self.ready_tree()
        fields = ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")
        for index, field in enumerate(fields):
            with self.subTest(field=field):
                wrong = "wrong@example.invalid" if field.endswith("EMAIL") else "Wrong Identity"
                bad = self.commit_tree(tree, self.old, b"identity\n\n" + EXACT + b"\n", {field: wrong})
                actual = self.fixture.git("show", "-s", "--format=%an%x00%ae%x00%cn%x00%ce", bad)
                expected = [
                    b"github-actions[bot]", b"github-actions[bot]@users.noreply.github.com",
                    b"github-actions[bot]", b"github-actions[bot]@users.noreply.github.com",
                ]
                expected[index] = wrong.encode()
                self.assertEqual(actual.removesuffix(b"\n").split(b"\0"), expected)
                self.select(bad)
                before = self.fixture.snapshot()
                result = self.hook("bump", self.old, bad)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"Actual Bump author AND committer", result.stderr)
                self.assertEqual(self.fixture.snapshot(), before)
                good = self.commit_tree(tree, self.old, b"identity\n\n" + EXACT + b"\n")
                self.assert_actual_bot_identities(good)
                self.select(good)
                result = self.hook("bump", self.old, good)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(self.fixture.snapshot(), before)

    def test_migration_does_not_require_bot_author_or_committer(self):
        self.fixture.git("fetch", "--quiet", "--depth=1", "--no-tags", str(ROOT), INTAKE)
        tree = self.fixture.git("write-tree").decode().strip()
        good = self.commit_tree(tree, INTAKE, b"migration\n\n" + EXACT + b"\n", {
            "GIT_AUTHOR_NAME": "Migration Owner", "GIT_AUTHOR_EMAIL": "owner@example.invalid",
            "GIT_COMMITTER_NAME": "Migration Committer", "GIT_COMMITTER_EMAIL": "committer@example.invalid",
        })
        self.select(good)
        result = self.hook("migration", "0"*40, good)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_migration_exact_old_new_correction_and_advertisement_literals(self):
        self.fixture.git("fetch", "--quiet", "--depth=1", "--no-tags", str(ROOT), INTAKE)
        tree = self.fixture.git("write-tree").decode().strip()
        first = self.commit_tree(tree, INTAKE, b"migration\n\n" + EXACT + b"\n")
        corrected = self.commit_tree(tree, first, b"correction\n\n" + EXACT + b"\n")
        self.select(corrected)
        for row in (
            "", f"refs/heads/master {corrected} refs/heads/master {first}\n",
            f"HEAD {corrected} refs/heads/wrong {first}\n",
            f"HEAD {first} refs/heads/master {first}\n",
            f"HEAD {corrected} refs/heads/master {'0'*40}\n",
            f"HEAD {corrected} refs/heads/master {first}\n" * 2,
        ):
            with self.subTest(row=row):
                self.assertNotEqual(self.hook("migration", first, corrected, row=row).returncode, 0)
                result = self.hook("migration", first, corrected)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
        result = self.hook(
            "migration", first, corrected,
            row=f"{corrected} {corrected} refs/heads/master {first}\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_migration_backend_rechecks_actual_committed_executable_each_invocation(self):
        self.fixture.git("fetch", "--quiet", "--depth=1", "--no-tags", str(ROOT), INTAKE)
        tree = self.fixture.git("write-tree").decode().strip()
        good = self.commit_tree(tree, INTAKE, b"migration\n\n" + EXACT + b"\n")
        self.select(good)
        hook = self.root / ".github/migration-hooks/pre-push"
        original = hook.read_bytes()
        for kind in ("missing", "nonexec", "exit0", "samebytes-symlink", "committed-missing", "committed-nonexec"):
            with self.subTest(kind=kind):
                new = good
                if kind == "missing":
                    hook.unlink()
                elif kind == "nonexec":
                    hook.chmod(0o644)
                elif kind == "exit0":
                    hook.write_bytes(b"#!/bin/sh\nexit 0\n")
                elif kind == "samebytes-symlink":
                    backup = self.root / ".git/migration-hook-backup"
                    backup.write_bytes(original)
                    backup.chmod(0o755)
                    hook.unlink()
                    hook.symlink_to(backup)
                else:
                    if kind == "committed-missing":
                        self.fixture.git("update-index", "--force-remove", "--", ".github/migration-hooks/pre-push")
                    else:
                        oid = self.fixture.git("rev-parse", "HEAD:.github/migration-hooks/pre-push").decode().strip()
                        self.fixture.git("update-index", "--cacheinfo", f"100644,{oid},.github/migration-hooks/pre-push")
                    new = self.commit_tree(self.fixture.git("write-tree").decode().strip(), INTAKE, b"bad guard\n\n" + EXACT + b"\n")
                    self.select(new)
                before = self.fixture.snapshot()
                result = subprocess.run(
                    [sys.executable, str(self.root / ".github/scripts/migration_guard.py")],
                    input=f"HEAD {new} refs/heads/master {'0'*40}\n".encode(), cwd=self.root,
                    env={**self.fixture.env, "MIGRATION_EXPECTED_OLD_SHA": "0"*40,
                         "MIGRATION_NEW_SHA": new, "MIGRATION_EXPECTED_REF": "refs/heads/master"},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"guard", result.stderr)
                self.assertEqual(self.fixture.snapshot(), before)
                if hook.is_symlink():
                    hook.unlink()
                hook.write_bytes(original)
                hook.chmod(0o755)
                self.fixture.git("read-tree", good)
                self.select(good)
                result = self.hook("migration", "0"*40, good)
                self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_actual_migration_git_hook_createzero_and_exact_guarded_correction(self):
        self.fixture.git("fetch", "--quiet", "--depth=1", "--no-tags", str(ROOT), INTAKE)
        tree = self.fixture.git("write-tree").decode().strip()
        first = self.commit_tree(tree, INTAKE, b"migration\n\n" + EXACT + b"\n")
        bare = self.root / ".git/migration-bare.git"
        self.fixture.git("init", "--quiet", "--bare", str(bare))
        self.fixture.git("--git-dir", str(bare), "fetch", "--quiet", "--depth=1", "--no-tags", str(ROOT), INTAKE)
        self.fixture.git("remote", "add", "origin", str(bare))
        ref = "refs/heads/offline-migration"
        self.select(first)
        for old, new in (("0"*40, first), (first, self.commit_tree(tree, first, b"correction\n\n" + EXACT + b"\n"))):
            with self.subTest(old=old, new=new):
                self.select(new)
                command = [
                    "git", "-c", f"core.hooksPath={self.root / '.github/migration-hooks'}",
                    "-c", "push.followTags=false", "push", "--no-follow-tags",
                    "origin", f"{new}:{ref}",
                ]
                env = {**self.fixture.env, "MIGRATION_EXPECTED_OLD_SHA": old,
                       "MIGRATION_NEW_SHA": new, "MIGRATION_EXPECTED_REF": ref}
                before = self.fixture.snapshot()
                result = subprocess.run(command, cwd=self.root, env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(self.fixture.snapshot(), before)
                self.assertEqual(self.fixture.git("--git-dir", str(bare), "rev-parse", ref).decode().strip(), new)
                self.assertEqual(self.fixture.git("--git-dir", str(bare), "tag", "--list"), b"")
                self.assertEqual(self.fixture.git("status", "--porcelain"), b"")
                self.assertNotIn("--force", command)
                self.assertIn("push.followTags=false", command)
                self.assertIn("--no-follow-tags", command)
                repeated = subprocess.run(command, cwd=self.root, env=env,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                self.assertNotEqual(repeated.returncode, 0)
                self.assertIn(b"exactly one advertised update", repeated.stderr)
                self.assertEqual(self.fixture.snapshot(), before)

    def test_bump_literal_advertisement_and_nonversion_source_change(self):
        tree = self.ready_tree()
        good = self.commit_tree(tree, self.old, b"bump\n\n" + EXACT + b"\n")
        self.select(good)
        for row in (
            "", f"refs/heads/master {good} refs/heads/master {self.old}\n",
            f"HEAD {good} refs/heads/master {'0'*40}\n",
            f"HEAD {good} refs/heads/master {self.old}\n" * 2,
        ):
            with self.subTest(row=row):
                self.assertNotEqual(self.hook("bump", self.old, good, row=row).returncode, 0)
                result = self.hook("bump", self.old, good)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
        project = self.root / source.PROJECT
        project.write_bytes(project.read_bytes() + b"\n// not a version edit\n")
        self.fixture.git("add", str(source.PROJECT))
        bad = self.commit_tree(self.fixture.git("write-tree").decode().strip(), self.old, b"bump\n\n" + EXACT + b"\n")
        self.select(bad)
        result = self.hook("bump", self.old, bad)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"other than exact version token spans", result.stderr)

    def bare(self):
        bare = self.root / ".git/offline-remote.git"
        self.fixture.git("init", "--quiet", "--bare", str(bare))
        self.fixture.git("remote", "add", "origin", str(bare))
        self.fixture.git("push", "--quiet", "origin", "HEAD:refs/heads/master")
        return bare

    def wrapper(self, mode="none", race_sha=None):
        executable = self.root / ".git/fixture-bin/git"
        executable.parent.mkdir()
        executable.write_bytes((ROOT / "tests/git_wrapper.py").read_bytes())
        executable.chmod(0o755)
        self.fixture.env.update({
            "FIXTURE_REAL_GIT": shutil.which("git"),
            "FIXTURE_ROOT": str(self.root),
            "FIXTURE_RACE": mode,
            "PATH": str(executable.parent) + os.pathsep + self.fixture.env["PATH"],
        })
        if race_sha is not None:
            self.fixture.env["FIXTURE_RACE_SHA"] = race_sha

    def test_initial_exit0_and_samebytes_symlink_no_edits_or_push_then_positive(self):
        self.bare()
        self.wrapper()
        hook = self.root / ".github/hooks/pre-push"
        raw = hook.read_bytes()
        for kind in ("exit0", "samebytes-symlink"):
            with self.subTest(kind=kind):
                if kind == "exit0":
                    hook.write_bytes(b"#!/bin/sh\nexit 0\n")
                    hook.chmod(0o755)
                else:
                    target = self.root / ".git/original-hook"
                    target.write_bytes(raw)
                    target.chmod(0o755)
                    hook.unlink()
                    hook.symlink_to(target)
                before = self.fixture.snapshot()
                old = self.fixture.git("rev-parse", "HEAD").decode().strip()
                result = self.fixture.cli("bump", "patch", "--sha", old, "--ref", "refs/heads/master")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.fixture.snapshot(), before)
                self.assertFalse((self.root / ".git/push-calls").exists())
                if hook.is_symlink():
                    hook.unlink()
                hook.write_bytes(raw)
                hook.chmod(0o755)
                result = self.fixture.cli("bump", "patch", "--sha", old, "--ref", "refs/heads/master")
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                (self.root / ".git/push-calls").unlink()

    def test_committed_missing_and_nonexecutable_guard_rejected_before_edits(self):
        for kind in ("missing", "nonexec"):
            with self.subTest(kind=kind):
                fixture = GitFixture(self)
                hook = fixture.root / ".github/hooks/pre-push"
                raw = hook.read_bytes()
                if kind == "missing":
                    hook.unlink()
                    fixture.git("add", "-u", "--", ".github/hooks/pre-push")
                else:
                    hook.chmod(0o644)
                    fixture.git("add", "--", ".github/hooks/pre-push")
                fixture.git("-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "bad fixture guard")
                old = fixture.git("rev-parse", "HEAD").decode().strip()
                if kind == "nonexec":
                    hook.chmod(0o755)
                before = fixture.snapshot()
                result = fixture.cli("bump", "patch", "--sha", old, "--ref", "refs/heads/master")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"guard", result.stderr)
                self.assertEqual(fixture.snapshot(), before)
                hook.write_bytes(raw)
                hook.chmod(0o755)
                fixture.git("add", "--", ".github/hooks/pre-push")
                fixture.git("-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "restore fixture guard")
                fixture.sha = fixture.git("rev-parse", "HEAD").decode().strip()
                bare = fixture.root / ".git/offline-remote.git"
                fixture.git("init", "--quiet", "--bare", str(bare))
                fixture.git("remote", "add", "origin", str(bare))
                fixture.git("push", "--quiet", "origin", "HEAD:refs/heads/master")
                result = fixture.cli("bump", "patch", "--sha", fixture.sha, "--ref", "refs/heads/master")
                self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_late_hook_swaps_after_second_real_remote_read_zero_push(self):
        for mode in ("late-exit0", "late-symlink"):
            with self.subTest(mode=mode):
                fixture = GitFixture(self)
                self.fixture, self.root, self.old = fixture, fixture.root, fixture.sha
                bare = self.bare()
                raw = (self.root / ".github/hooks/pre-push").read_bytes()
                self.wrapper(mode)
                result = fixture.cli("bump", "patch", "--sha", self.old, "--ref", "refs/heads/master")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.root / ".git/remote-reads").read_text(), "2")
                self.assertFalse((self.root / ".git/push-calls").exists())
                self.assertEqual(fixture.git("--git-dir", str(bare), "rev-parse", "refs/heads/master").decode().strip(), self.old)
                new = fixture.git("rev-parse", "HEAD").decode().strip()
                self.assertNotEqual(new, self.old)
                self.assertEqual(source.read(self.root), "2.1.7")
                hook = self.root / ".github/hooks/pre-push"
                if hook.is_symlink():
                    hook.unlink()
                hook.write_bytes(raw)
                hook.chmod(0o755)
                before = fixture.snapshot()
                result = self.hook("bump", self.old, new)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(fixture.snapshot(), before)
                self.assertFalse((self.root / ".git/push-calls").exists())

    def test_actual_bare_advertisement_advance_rewind_delete_same_result(self):
        for mode in ("advance", "rewind", "delete", "same-result"):
            with self.subTest(mode=mode):
                fixture = GitFixture(self)
                self.fixture, self.root = fixture, fixture.root
                parent = fixture.sha
                fixture.git("-c", "commit.gpgSign=false", "commit", "--quiet", "--allow-empty", "-m", "selected fixture")
                self.old = fixture.git("rev-parse", "HEAD").decode().strip()
                fixture.sha = self.old
                bare = self.bare()
                race_sha = parent
                if mode == "advance":
                    tree = fixture.git("rev-parse", "HEAD^{tree}").decode().strip()
                    race_sha = self.commit_tree(tree, self.old, b"external fixture advance\n")
                    fixture.git("--git-dir", str(bare), "fetch", "--quiet", "--no-tags", str(self.root), race_sha)
                self.wrapper(mode, race_sha)
                result = fixture.cli("bump", "patch", "--sha", self.old, "--ref", "refs/heads/master")
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue((self.root / ".git/push-calls").exists())
                expected = (self.root / ".git/raced-remote").read_text()
                actual = fixture.git("--git-dir", str(bare), "for-each-ref", "--format=%(objectname)", "refs/heads/master").decode().strip()
                self.assertEqual(actual, "" if expected == "DELETED" else expected)
                self.assertEqual(fixture.git("--git-dir", str(bare), "for-each-ref", "--format=%(refname)", "refs/tags"), b"")
                self.assertEqual(source.read(self.root), "2.1.7")

    def test_nonforce_cas_after_successful_real_advertisement_guard(self):
        hook = self.root / ".github/hooks/pre-push"
        hook.write_bytes(hook.read_bytes().replace(b"exec python3", b"python3") + (
            b'"$FIXTURE_REAL_GIT" --git-dir "$FIXTURE_REMOTE" update-ref refs/heads/master "$FIXTURE_RACE_SHA"\n'
        ))
        self.fixture.git("add", ".github/hooks/pre-push")
        self.fixture.git("-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "fixture postguard race hook")
        self.old = self.fixture.git("rev-parse", "HEAD").decode().strip()
        bare = self.bare()
        tree = self.fixture.git("rev-parse", "HEAD^{tree}").decode().strip()
        advance = self.commit_tree(tree, self.old, b"external postadvertisement advance\n")
        self.fixture.git("--git-dir", str(bare), "fetch", "--quiet", "--no-tags", str(self.root), advance)
        self.fixture.env.update({
            "FIXTURE_REAL_GIT": shutil.which("git"),
            "FIXTURE_REMOTE": str(bare), "FIXTURE_RACE_SHA": advance,
        })
        result = self.fixture.cli("bump", "patch", "--sha", self.old, "--ref", "refs/heads/master")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.fixture.git("--git-dir", str(bare), "rev-parse", "refs/heads/master").decode().strip(), advance)
        self.assertIn(b"failed", result.stderr)

    def test_actual_minor_and_major_bump_cli(self):
        for mode, expected in (("minor", "2.2.0"), ("major", "3.0.0")):
            with self.subTest(mode=mode):
                fixture = GitFixture(self)
                bare = fixture.root / ".git/offline-remote.git"
                fixture.git("init", "--quiet", "--bare", str(bare))
                fixture.git("remote", "add", "origin", str(bare))
                fixture.git("push", "--quiet", "origin", "HEAD:refs/heads/master")
                fixture.git("checkout", "--quiet", "--detach", fixture.sha)
                for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
                    fixture.env.pop(key, None)
                result = fixture.cli("bump", mode, "--sha", fixture.sha, "--ref", "refs/heads/master")
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(source.read(fixture.root), expected)

    def test_actual_bump_detached_bot_three_sources_and_followtags_negative_control(self):
        bare = self.bare()
        self.wrapper()
        self.fixture.git("-c", "tag.gpgSign=false", "tag", "-a", "fixture-annotated", "-m", "fixture")
        self.fixture.git("config", "push.followTags", "true")
        self.fixture.git("checkout", "--quiet", "--detach", self.old)
        for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
            self.fixture.env.pop(key, None)
        before = self.fixture.sha
        result = self.fixture.cli("bump", "patch", "--sha", before, "--ref", "refs/heads/master")
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        new = self.fixture.git("rev-parse", "HEAD").decode().strip()
        self.assertEqual(self.fixture.git("--git-dir", str(bare), "rev-parse", "refs/heads/master").decode().strip(), new)
        self.assertEqual(self.fixture.git("rev-list", "--parents", "-n", "1", new).decode().strip(), f"{new} {before}")
        self.assertEqual(set(self.fixture.git("diff-tree", "--no-commit-id", "--name-only", "-r", new).decode().splitlines()),
                         {"ImageCaptureCore.xcodeproj/project.pbxproj", "Info.plist", "English.lproj/InfoPlist.strings"})
        self.assertEqual(source.read(self.root), "2.1.7")
        self.assertEqual(self.fixture.git("show", "-s", "--format=%an|%ae|%cn|%ce", new).decode().strip(),
                         "github-actions[bot]|github-actions[bot]@users.noreply.github.com|github-actions[bot]|github-actions[bot]@users.noreply.github.com")
        self.assertEqual(self.fixture.git("cat-file", "commit", new).split(b"\n\n", 1)[1][:-1].rsplit(b"\n", 1)[-1], EXACT)
        self.assertEqual(self.fixture.git("--git-dir", str(bare), "for-each-ref", "--format=%(refname)", "refs/tags"), b"")
        pushes = [json.loads(line) for line in (self.root / ".git/push-calls").read_text().splitlines()]
        self.assertEqual(len(pushes), 1)
        self.assertIn("push.followTags=false", pushes[0])
        self.assertIn("--no-follow-tags", pushes[0])
        control = self.root / ".git/tag-control.git"
        self.fixture.git("init", "--quiet", "--bare", str(control))
        self.fixture.git("-c", "push.followTags=true", "push", "--quiet", str(control), "HEAD:refs/heads/control")
        self.assertEqual(self.fixture.git("--git-dir", str(control), "for-each-ref", "--format=%(refname)", "refs/tags"),
                         b"refs/tags/fixture-annotated\n")


if __name__ == "__main__":
    unittest.main()
