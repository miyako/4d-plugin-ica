import sys

sys.dont_write_bytecode = True

import errno
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from tests.git_fixture import GitFixture, policy
from tests.helper_support import helper


repository = helper("repository")
physical = helper("physical")


class RepositoryNativeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = GitFixture(self)
        self.root = self.fixture.root

    def positive(self, name="repository", *args):
        result = self.fixture.cli(name, *args, "--sha", self.fixture.sha)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result

    def rejected(self, name="repository", *args):
        before = self.fixture.snapshot()
        result = self.fixture.cli(name, *args, "--sha", self.fixture.sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.fixture.snapshot(), before)
        return result

    def test_selected_index_and_raw_are_separate(self):
        self.positive()
        project = "ImageCaptureCore.xcodeproj/project.pbxproj"
        before = (self.root / project).read_bytes()
        (self.root / project).write_bytes(before + b"\n")
        self.fixture.git("add", project)
        (self.root / project).write_bytes(before)
        self.rejected()
        self.fixture.git("reset", "--quiet", "HEAD", "--", project)
        self.positive()
        (self.root / project).write_bytes(before + b"\n")
        self.rejected()
        (self.root / project).write_bytes(before)
        self.positive()

    def test_both_real_git_flags_fsmonitor_h_oracle_then_restored(self):
        for name in ("ImageCaptureCore.xcodeproj/project.pbxproj", policy.EXECUTABLE):
            with self.subTest(path=name):
                hook = self.root / ".git/hooks/fsmonitor-fixture"
                hook.write_text("#!/bin/sh\nprintf 'fixture-clock\\000'\n")
                hook.chmod(0o755)
                self.fixture.git("config", "core.fsmonitor", str(hook))
                self.fixture.git("update-index", "--fsmonitor")
                self.fixture.git("update-index", "--fsmonitor-valid", "--", name)
                self.assertEqual(self.fixture.git("ls-files", "-v", "--", name)[:2], b"H ")
                self.assertEqual(self.fixture.git("ls-files", "-f", "--", name)[:2], b"h ")
                self.rejected()
                self.fixture.generated()
                self.rejected("native", "final")
                self.fixture.git("config", "--unset", "core.fsmonitor")
                self.fixture.git("update-index", "--no-fsmonitor")
                self.fixture.restore_selected()
                self.positive()
                self.fixture.generated()
                before = self.fixture.snapshot()
                self.positive("native", "final")
                self.assertEqual(self.fixture.snapshot(), before)
                self.fixture.restore_selected()

    def test_assume_unchanged_skip_worktree_and_index_generated_rejected(self):
        name = policy.EXECUTABLE
        for flag, undo in (("--assume-unchanged", "--no-assume-unchanged"),
                           ("--skip-worktree", "--no-skip-worktree")):
            with self.subTest(flag=flag):
                self.fixture.git("update-index", flag, "--", name)
                self.rejected()
                self.rejected("native", "final")
                self.fixture.git("update-index", undo, "--", name)
                self.positive()
        self.fixture.write(name, b"staged generated change")
        self.fixture.git("add", name)
        self.fixture.write(name, self.fixture.git("show", "HEAD:" + name))
        self.rejected("native", "final")
        self.fixture.git("reset", "--quiet", "HEAD", "--", name)
        self.positive()

    def test_final_retains_generated_and_fresh_exact_database(self):
        self.fixture.generated()
        database = self.fixture.write(policy.XC + "/build.db", b"fresh native DB")
        before = self.fixture.snapshot()
        self.positive("native", "final")
        self.assertEqual(self.fixture.snapshot(), before)
        self.rejected()
        self.assertEqual(database.read_bytes(), b"fresh native DB")

    def test_narrow_output_classifier_independent_literals(self):
        for name in (
            "test/Plugins/XCBuildData/build.db",
            "test/Plugins/XCBuildData/build.db-wal",
            "test/Plugins/XCBuildData/build.db-shm",
            "test/Plugins/XCBuildData/" + "a" * 32 + ".xcbuilddata/description.msgpack",
            "test/Plugins/ImageCaptureCore.build/Default/ImageCaptureCore.build/ImageCaptureCore-generated-files.hmap",
            "test/Plugins/ImageCaptureCore.build/Default/ImageCaptureCore.build/Objects-normal/arm64/C_TEXT.o",
        ):
            with self.subTest(path=name):
                self.assertTrue(policy.generated_file(name))
        for name in (
            "build/not-generated.cpp",
            "test/Plugins/XCBuildData-evil/build.db",
            "test/Plugins/XCBuildData/build.db-evil",
            "test/Plugins/XCBuildData/unexpected-source.cpp",
            "test/Plugins/XCBuildData/evil.xcbuilddata/description.msgpack",
            "test/Plugins/XCBuildData/" + "A" * 32 + ".xcbuilddata/description.msgpack",
            "test/Plugins/ExplicitPrecompiledModules/arbitrary.cpp",
            "test/Plugins/SwiftExplicitPrecompiledModules/arbitrary.pcm",
            "test/Plugins/Default/keep.txt",
        ):
            with self.subTest(path=name):
                self.assertFalse(policy.generated_file(name))

    def test_each_unexpected_ignored_output_retained_then_positive(self):
        self.fixture.generated()
        for name in (
            "ignored/unexpected-source.cpp", policy.XC + "/build.db-evil",
            policy.XC + "/unexpected-source.cpp", policy.OUTPUT + "/XCBuildData-evil/build.db",
            policy.XC + "/evil.xcbuilddata/description.msgpack",
        ):
            with self.subTest(path=name):
                path = self.fixture.write(name, b"must retain")
                self.rejected("native", "final")
                path.unlink()
                self.positive("native", "final")

    def test_each_packaged_leaf_physical_negative_then_same_fixture_positive(self):
        self.fixture.generated()
        for name in sorted(policy.PACKAGE_LEAVES):
            path = self.root / name
            original = path.read_bytes()
            for kind in ("missing", "empty", "directory", "samebytes-symlink"):
                with self.subTest(path=name, kind=kind):
                    backup = self.root / ".git/leaf-backup"
                    backup.write_bytes(original)
                    path.unlink()
                    if kind == "empty":
                        path.write_bytes(b"")
                    elif kind == "directory":
                        path.mkdir()
                    elif kind == "samebytes-symlink":
                        path.symlink_to(backup)
                    self.rejected("native", "final")
                    if path.is_symlink() or path.is_file():
                        path.unlink()
                    elif path.exists():
                        path.rmdir()
                    path.write_bytes(original)
                    before = self.fixture.snapshot()
                    self.positive("native", "final")
                    self.assertEqual(self.fixture.snapshot(), before)

    def test_each_copied_resource_drift_then_positive(self):
        self.fixture.generated()
        for dest in policy.COPIED_RESOURCES:
            path = self.root / dest
            before = path.read_bytes()
            path.write_bytes(before + b"drift")
            self.rejected("native", "final")
            path.write_bytes(before)
            self.positive("native", "final")

    def test_cleanup_all_enclosing_markers_and_modes_atomic_each_then_positive(self):
        parents = (
            "test", "test/Plugins", policy.CONTENTS, policy.CONTENTS + "/_CodeSignature",
            policy.CONTENTS + "/MacOS", policy.CONTENTS + "/Resources/English.lproj",
        )
        for parent in parents:
            kinds = ("marker-file", "marker-directory", "marker-link", "search-only")
            if parent not in ("test", "test/Plugins"):
                kinds += ("read-only",)
            for kind in kinds:
                with self.subTest(parent=parent, kind=kind):
                    directory = self.root / parent
                    marker = directory / ".git"
                    if kind == "marker-file":
                        marker.write_bytes(b"gitdir: forbidden")
                    elif kind == "marker-directory":
                        marker.mkdir()
                    elif kind == "marker-link":
                        marker.symlink_to(self.root / ".git")
                    else:
                        directory.chmod(0o111 if kind == "search-only" else 0o555)
                    try:
                        self.rejected("native", "cleanup")
                    finally:
                        if kind == "marker-directory":
                            marker.rmdir()
                        elif kind.startswith("marker"):
                            marker.unlink()
                        else:
                            directory.chmod(0o755)
                    self.positive("native", "cleanup")
                    for leaf in policy.GENERATED_LEAVES:
                        self.assertFalse((self.root / leaf).exists())
                    for leaf in policy.COPIED_RESOURCES.keys() | set(policy.PRESERVED_LEAVES):
                        self.assertTrue((self.root / leaf).is_file())
                    self.fixture.restore_selected()

    def test_cleanup_late_types_symlinks_fifo_and_descendant_access_atomic(self):
        for kind in ("directory-as-file", "symlink", "fifo", "file-as-directory",
                     "unreadable-child", "nested-marker"):
            with self.subTest(kind=kind):
                late = self.root / policy.SIGNATURE
                directory = self.root / policy.DIRECTORY_TARGETS[0]
                if kind in ("directory-as-file", "symlink", "fifo"):
                    raw = late.read_bytes()
                    late.unlink()
                    if kind == "directory-as-file":
                        late.mkdir()
                    elif kind == "symlink":
                        late.symlink_to(self.root / ".git/config")
                    else:
                        os.mkfifo(late)
                elif kind == "file-as-directory":
                    directory.write_bytes(b"not a directory")
                else:
                    child = directory / "Default"
                    child.mkdir(parents=True)
                    if kind == "unreadable-child":
                        child.chmod(0o111)
                    else:
                        (child / ".git").write_bytes(b"nested")
                self.rejected("native", "cleanup")
                if kind == "directory-as-file":
                    late.rmdir()
                    late.write_bytes(raw)
                elif kind in ("symlink", "fifo"):
                    late.unlink()
                    late.write_bytes(raw)
                elif kind == "file-as-directory":
                    directory.unlink()
                else:
                    child.chmod(0o755)
                    if kind == "nested-marker":
                        (child / ".git").unlink()
                self.positive("native", "cleanup")
                self.fixture.restore_selected()

    def test_cleanup_only_enoent_absence_and_no_selected_intermediate_deletion(self):
        for number in (errno.EACCES, errno.EIO, errno.ENOTDIR):
            with self.subTest(errno=number), patch.object(
                physical, "optional_lstat", side_effect=OSError(number, "fixture fault"),
            ):
                before = self.fixture.snapshot()
                with self.assertRaises(OSError):
                    physical.cleanup_plan(self.root, [(policy.SIGNATURE, "file")], allowed_file=lambda p: True)
                self.assertEqual(self.fixture.snapshot(), before)
        for invalid in ("../escape", "/absolute"):
            with self.assertRaises(ValueError):
                physical.cleanup_plan(self.root, [(invalid, "file")], allowed_file=lambda p: True)
        name = policy.TARGET_TEMP + "/Objects-normal/arm64/C_TEXT.o"
        self.fixture.write(name, b"selected input despite generated-looking name")
        self.fixture.git("add", name)
        self.fixture.git("-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "selected fixture input")
        self.fixture.sha = self.fixture.git("rev-parse", "HEAD").decode().strip()
        self.rejected("native", "cleanup")
        self.assertEqual((self.root / name).read_bytes(), b"selected input despite generated-looking name")
        self.fixture.git("rm", "--quiet", name)
        self.fixture.git("-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "restore fixture input scope")
        self.fixture.sha = self.fixture.git("rev-parse", "HEAD").decode().strip()
        self.positive("native", "cleanup")

    def test_empty_configuration_sibling_is_never_deleted(self):
        for relative in (
            policy.PROJECT_TEMP + "/Deployment",
            policy.PROJECT_TEMP + "/Default/another.build",
            policy.OUTPUT + "/EagerLinkingTBDs/Development",
            policy.OUTPUT + "/ExplicitPrecompiledModules/arbitrary",
        ):
            with self.subTest(path=relative):
                sibling = self.root / relative
                sibling.mkdir(parents=True)
                self.rejected("native", "cleanup")
                self.assertTrue(sibling.is_dir())
                sibling.rmdir()
                self.positive("native", "cleanup")
                self.fixture.restore_selected()

    def test_selected_prebuilt_mode_and_bytes_must_remain_exact(self):
        self.fixture.generated()
        for name in policy.PRESERVED_LEAVES:
            path = self.root / name
            mode = path.stat().st_mode & 0o777
            raw = path.read_bytes()
            path.chmod(0o755)
            self.rejected("native", "final")
            path.chmod(mode)
            self.positive("native", "final")
            path.write_bytes(raw + b"drift")
            self.rejected("native", "final")
            path.write_bytes(raw)
            self.positive("native", "final")


if __name__ == "__main__":
    unittest.main()
