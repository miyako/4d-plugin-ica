import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import unittest

from tests.git_fixture import GitFixture, policy


class PublicationFixture:
    def setUp(self):
        self.fixture = GitFixture(self)
        self.root = self.fixture.root
        real_git = shutil.which("git")
        self.fixture.git("init", "--quiet", "--bare", str(self.root / ".git/offline-api.git"))
        self.fixture.git("remote", "add", "origin", str(self.root / ".git/offline-api.git"))
        self.fixture.git("push", "--quiet", "--no-follow-tags", "origin", "HEAD:refs/heads/master")
        self.fixture.git("-c", "commit.gpgSign=false", "commit", "--allow-empty", "--quiet", "-m", "other fixture object")
        self.other_sha = self.fixture.git("rev-parse", "HEAD").decode().strip()
        self.fixture.git("push", "--quiet", "--no-follow-tags", "origin", "HEAD:refs/heads/other")
        self.fixture.git("checkout", "--quiet", "--detach", self.fixture.sha)
        executable = self.root / ".git/fixture-bin/gh"
        executable.parent.mkdir()
        executable.write_bytes(
            ("#!" + sys.executable + "\n").encode() + (Path(__file__).parent / "fake_gh.py").read_bytes(),
        )
        executable.chmod(0o755)
        self.fixture.env.update(
            PATH=str(executable.parent) + os.pathsep + os.environ["PATH"],
            FIXTURE_REAL_GIT=real_git, GH_TOKEN="offline-installation-token",
            GITHUB_REPOSITORY="miyako/4d-plugin-ica",
        )
        self.state_path = self.root / ".git/fake-api.json"
        self.reset_api()

    def reset_api(self, mode="positive"):
        # Disposable fixture reset only; production publication has no delete/retry path.
        subprocess.run(
            [self.fixture.env["FIXTURE_REAL_GIT"], "--git-dir", str(self.root / ".git/offline-api.git"),
             "update-ref", "-d", "refs/tags/v2.1.6"],
            check=True, env=self.fixture.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self.state_path.write_text(json.dumps({
            "mode": mode, "calls": [], "sha": self.fixture.sha, "tag": "v2.1.6",
            "other_sha": self.other_sha, "ref_created": False, "release_created": False, "assets": [],
        }))

    def state(self):
        return json.loads(self.state_path.read_text())

    def prepare(self):
        self.fixture.generated()
        for suffix in ("zip", "dmg"):
            self.fixture.write(f"ImageCaptureCore-2.1.6.{suffix}", ("new " + suffix + " archive").encode())
        self.fixture.write("test/Plugins/XCBuildData/build.db", b"fresh native DB retained")

    def call(self, phase="publish"):
        return self.fixture.cli("publication", phase, "--sha", self.fixture.sha)

    def positive(self, phase="publish"):
        before = self.fixture.snapshot()
        result = self.call(phase)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(self.fixture.snapshot(), before)
        return result

    def local_negative(self, phase="publish"):
        before = self.fixture.snapshot()
        result = self.call(phase)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state()["calls"], [], result.stderr.decode())
        self.assertEqual(self.fixture.snapshot(), before)
        return result


class PublicationTests(PublicationFixture, unittest.TestCase):
    def test_entire_compiled_localization_name_and_extra_key_zero_api_each_restored(self):
        self.prepare()
        path = self.root / policy.BUILT_ENGLISH
        original = path.read_bytes()
        for kind in ("missing-name", "drift-name", "extra-key"):
            with self.subTest(kind=kind):
                self.reset_api()
                value = plistlib.loads(original)
                if kind == "missing-name":
                    del value["CFBundleName"]
                elif kind == "drift-name":
                    value["CFBundleName"] = "Wrong product"
                else:
                    value["UnselectedExtraKey"] = "must reject"
                path.write_bytes(plistlib.dumps(value, fmt=plistlib.FMT_BINARY))
                index = self.fixture.git("ls-files", "--stage", "-z")
                result = self.local_negative()
                self.assertIn(b"localized dictionary", result.stderr)
                self.assertEqual(self.fixture.git("ls-files", "--stage", "-z"), index)
                path.write_bytes(original)
                self.positive()

    def test_selected_entire_extra_keys_and_supported_version_refs_preserved_and_checked(self):
        path = self.root / "English.lproj/InfoPlist.strings"
        source_bytes = path.read_bytes().replace(
            b'CFBundleShortVersionString = "2.1.6";', b'CFBundleShortVersionString = "$(MARKETING_VERSION)";',
        ) + (b'AdditionalVersion = "${CURRENT_PROJECT_VERSION}";\r'
             b'AdditionalName = "Preserve extra name";\rAdditionalText = "Preserve extra text";\r')
        path.write_bytes(source_bytes)
        self.fixture.git("add", "--", "English.lproj/InfoPlist.strings")
        self.fixture.git("-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "fixture selected extra localization")
        self.fixture.sha = self.fixture.git("rev-parse", "HEAD").decode().strip()
        self.fixture.git("push", "--quiet", "--no-follow-tags", "origin", "HEAD:refs/heads/selected-extra")
        self.prepare()
        compiled = self.root / policy.BUILT_ENGLISH
        value = plistlib.loads(compiled.read_bytes())
        value["CFBundleShortVersionString"] = "2.1.6"
        value["AdditionalVersion"] = "2.1.6"
        compiled.write_bytes(plistlib.dumps(value, fmt=plistlib.FMT_BINARY))
        original = compiled.read_bytes()
        self.reset_api()
        self.positive()
        self.assertEqual(path.read_bytes(), source_bytes)
        for key in ("AdditionalVersion", "AdditionalName", "AdditionalText"):
            for kind in ("missing", "drift"):
                with self.subTest(key=key, kind=kind):
                    self.reset_api()
                    altered = dict(value)
                    if kind == "missing":
                        del altered[key]
                    else:
                        altered[key] = "changed"
                    compiled.write_bytes(plistlib.dumps(altered, fmt=plistlib.FMT_BINARY))
                    index = self.fixture.git("ls-files", "--stage", "-z")
                    self.local_negative()
                    self.assertEqual(self.fixture.git("ls-files", "--stage", "-z"), index)
                    compiled.write_bytes(original)
                    self.positive()
                    self.assertEqual(path.read_bytes(), source_bytes)

    def test_installation_token_canonical_independent_actual_cli_and_until_empty(self):
        self.positive("check")
        self.assertEqual([call["endpoint"] for call in self.state()["calls"]], [
            "repos/miyako/4d-plugin-ica",
            "repos/miyako/4d-plugin-ica/releases?per_page=100&page=1",
            "repos/miyako/4d-plugin-ica/releases?per_page=100&page=2",
            "repos/miyako/4d-plugin-ica/git/matching-refs/tags/v2.1.6",
        ])
        self.prepare()
        self.reset_api("three-pages")
        self.positive()
        state = self.state()
        self.assertEqual(state["assets"], ["ImageCaptureCore-2.1.6.zip", "ImageCaptureCore-2.1.6.dmg"])
        self.assertIn("repos/miyako/4d-plugin-ica/releases?per_page=100&page=3",
                      [call["endpoint"] for call in state["calls"]])
        self.assertEqual([call["method"] for call in state["calls"]].count("POST"), 4)
        self.assertFalse(any("/user" in call["endpoint"] for call in state["calls"]))
        self.assertEqual(
            self.fixture.git("ls-remote", "--refs", "origin", "refs/tags/v2.1.6").decode().strip(),
            self.fixture.sha + "\trefs/tags/v2.1.6",
        )
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", self.fixture.env)
        self.assertNotIn("PYTHONPYCACHEPREFIX", self.fixture.env)
        self.assertFalse(list(self.root.rglob("__pycache__")))

    def test_explicit_token_and_exact_canonical_env_before_api_each_restored_positive(self):
        self.prepare()
        for key, bad in (("GH_TOKEN", ""), ("GH_TOKEN", "  "),
                         ("GITHUB_REPOSITORY", "miyako/4d-plugin-ICA")):
            with self.subTest(key=key, bad=bad):
                original = self.fixture.env[key]
                self.fixture.env[key] = bad
                self.reset_api()
                self.local_negative()
                self.fixture.env[key] = original
                self.positive()

    def test_full_api_failure_matrix_retains_partial_without_retry_or_destructive_calls(self):
        self.prepare()
        modes = (
            "auth-failure", "repo-404", "repo-network", "repo-id", "repo-id-bool", "repo-case", "later-page-failure",
            "duplicate-json", "nonfinite-json", "overflow-json", "malformed-json", "scalar-page", "draft-match",
            "duplicate-release-id", "release-id-bool", "release-draft-type",
            "matching-refs-failure", "matching-refs-schema", "matching-ref-object",
            "matching-ref-duplicate", "matching-ref-unrelated",
            "matching-ref-sha", "api-tag", "tag-race", "post-ref-failure", "post-ref-sha",
            "verify-ref-failure", "verify-ref-sha", "verify-ref-type", "verify-remote-sha",
            "post-release-failure", "new-id-bool", "new-id-zero", "reused-id", "new-tag",
            "new-name", "new-target", "new-draft", "new-prerelease", "new-body", "new-upload-url",
            "upload-1-failure", "upload-2-failure", "asset-id-bool", "asset-name",
            "asset-size-bool", "asset-size", "asset-state", "asset-id-duplicate",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                self.reset_api(mode)
                before = self.fixture.snapshot()
                result = self.call()
                self.assertNotEqual(result.returncode, 0, mode)
                self.assertIn(b"retained", result.stderr)
                self.assertEqual(self.fixture.snapshot(), before)
                state = self.state()
                calls = [(call["method"], call["endpoint"]) for call in state["calls"]]
                self.assertTrue(all(method in ("GET", "POST") for method, _ in calls))
                self.assertEqual(len(calls), len(set(calls)), "No retry of any endpoint")
                tag = self.fixture.git("ls-remote", "--refs", "origin", "refs/tags/v2.1.6")
                if state["ref_created"]:
                    self.assertTrue(tag, "Partial created tag must remain")
                if mode == "upload-2-failure":
                    self.assertEqual(state["assets"], ["ImageCaptureCore-2.1.6.zip"])
                if state["release_created"]:
                    self.assertTrue(state["ref_created"])

    def test_existing_advertised_tag_and_remote_failure_no_mutations_then_restored(self):
        self.prepare()
        self.fixture.git("--git-dir", str(self.root / ".git/offline-api.git"),
                         "update-ref", "refs/tags/v2.1.6", self.fixture.sha)
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call["method"] == "POST" for call in self.state()["calls"]))
        self.reset_api()
        self.positive()
        self.reset_api()
        self.fixture.git("remote", "set-url", "origin", str(self.root / ".git/nonexistent.git"))
        before = self.fixture.snapshot()
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(call["method"] == "POST" for call in self.state()["calls"]))
        self.assertEqual(self.fixture.snapshot(), before)
        self.fixture.git("remote", "set-url", "origin", str(self.root / ".git/offline-api.git"))
        self.reset_api()
        self.positive()

    def test_actual_final_selected_index_raw_and_hidden_flags_each_restored_positive(self):
        self.prepare()
        project = "ImageCaptureCore.xcodeproj/project.pbxproj"
        for name in (project, policy.EXECUTABLE):
            path = self.root / name
            data = path.read_bytes()
            for kind in ("assume-unchanged", "skip-worktree", "reversed-stage", "index-mode"):
                with self.subTest(path=name, kind=kind):
                    self.reset_api()
                    if kind in ("assume-unchanged", "skip-worktree"):
                        self.fixture.git("update-index", "--" + kind, "--", name)
                    elif kind == "reversed-stage":
                        path.write_bytes(data + b"staged mismatch")
                        self.fixture.git("add", "--", name)
                        path.write_bytes(data)
                    else:
                        self.fixture.git("update-index", "--chmod=+x", "--", name)
                    self.local_negative()
                    if kind in ("assume-unchanged", "skip-worktree"):
                        self.fixture.git("update-index", "--no-" + kind, "--", name)
                    else:
                        self.fixture.git("reset", "--quiet", "HEAD", "--", name)
                    self.positive()
        path = self.root / project
        data = path.read_bytes()
        self.reset_api()
        path.write_bytes(data + b"\n")
        self.local_negative()
        path.write_bytes(data)
        self.positive()
        self.reset_api()
        self.fixture.git("-c", "commit.gpgSign=false", "commit", "--allow-empty", "--quiet", "-m", "wrong HEAD")
        self.local_negative()
        self.fixture.git("update-ref", "--no-deref", "HEAD", self.fixture.sha)
        self.positive()

    def test_each_archive_missing_empty_directory_symlink_before_api_then_retained_positive(self):
        self.prepare()
        for suffix in ("zip", "dmg"):
            path = self.root / f"ImageCaptureCore-2.1.6.{suffix}"
            data = path.read_bytes()
            for kind in ("missing", "empty", "directory", "samebytes-symlink"):
                with self.subTest(suffix=suffix, kind=kind):
                    self.reset_api()
                    backup = self.root / ".git/archive-backup"
                    backup.write_bytes(data)
                    path.unlink()
                    if kind == "empty":
                        path.write_bytes(b"")
                    elif kind == "directory":
                        path.mkdir()
                    elif kind == "samebytes-symlink":
                        path.symlink_to(backup)
                    self.local_negative()
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                    elif path.exists():
                        path.rmdir()
                    path.write_bytes(data)
                    self.positive()

    def test_each_packaged_leaf_negative_actual_final_cli_then_same_fixture_positive(self):
        self.prepare()
        for name in sorted(policy.PACKAGE_LEAVES):
            path = self.root / name
            data, mode = path.read_bytes(), path.stat().st_mode & 0o777
            for kind in ("missing", "empty", "directory", "samebytes-symlink"):
                with self.subTest(path=name, kind=kind):
                    self.reset_api()
                    backup = self.root / ".git/packaged-backup"
                    backup.write_bytes(data)
                    backup.chmod(mode)
                    path.unlink()
                    if kind == "empty":
                        path.write_bytes(b"")
                    elif kind == "directory":
                        path.mkdir()
                    elif kind == "samebytes-symlink":
                        path.symlink_to(backup)
                    self.local_negative()
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                    elif path.exists():
                        path.rmdir()
                    path.write_bytes(data)
                    path.chmod(mode)
                    self.positive()

    def test_actual_final_resource_prebuilt_and_narrow_output_negatives_each_restored(self):
        self.prepare()
        for name in (*policy.COPIED_RESOURCES, *policy.PRESERVED_LEAVES):
            with self.subTest(path=name):
                path = self.root / name
                original = path.read_bytes()
                self.reset_api()
                path.write_bytes(original + b"drift")
                self.local_negative()
                path.write_bytes(original)
                self.positive()
        for name in (
            "ignored/unexpected-source.cpp", "test/Plugins/XCBuildData-evil/build.db",
            "test/Plugins/XCBuildData/unexpected-source.cpp", "test/Plugins/XCBuildData/build.db-evil",
            "test/Plugins/XCBuildData/evil.xcbuilddata/description.msgpack",
        ):
            with self.subTest(path=name):
                self.reset_api()
                path = self.fixture.write(name, b"unexpected retained source")
                self.local_negative()
                path.unlink()
                self.positive()

    def test_actual_source_and_final_both_flags_real_fsmonitor_independent_h_h_oracle(self):
        for name in ("ImageCaptureCore.xcodeproj/project.pbxproj", policy.EXECUTABLE):
            with self.subTest(path=name):
                self.reset_api()
                hook = self.root / ".git/hooks/fsmonitor-fixture"
                hook.write_text("#!/bin/sh\nprintf 'fixture-clock\\000'\n")
                hook.chmod(0o755)
                self.fixture.git("config", "core.fsmonitor", str(hook))
                self.fixture.git("update-index", "--fsmonitor")
                self.fixture.git("update-index", "--fsmonitor-valid", "--", name)
                self.assertEqual(self.fixture.git("ls-files", "-v", "--", name)[:2], b"H ")
                self.assertEqual(self.fixture.git("ls-files", "-f", "--", name)[:2], b"h ")
                self.local_negative("check")
                self.prepare()
                self.local_negative()
                self.fixture.git("config", "--unset", "core.fsmonitor")
                self.fixture.git("update-index", "--no-fsmonitor")
                self.fixture.restore_selected()
                for suffix in ("zip", "dmg"):
                    (self.root / f"ImageCaptureCore-2.1.6.{suffix}").unlink()
                (self.root / "test/Plugins/XCBuildData/build.db").unlink()
                self.positive("check")
                self.prepare()
                self.reset_api()
                self.positive()
                self.fixture.restore_selected()
                for suffix in ("zip", "dmg"):
                    (self.root / f"ImageCaptureCore-2.1.6.{suffix}").unlink()
                (self.root / "test/Plugins/XCBuildData/build.db").unlink()
