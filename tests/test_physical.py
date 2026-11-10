import errno
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.helper_support import fixture, helper


physical = helper("physical")


class PhysicalTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture(self)
        self.relative = Path("test/Plugins/leaf")
        self.leaf = self.root / self.relative
        self.leaf.parent.mkdir(parents=True)
        self.leaf.write_bytes(b"selected bytes")

    def test_regular_and_legitimate_root_git_metadata(self):
        (self.root / ".git").mkdir()
        self.assertEqual(physical.regular_file(self.root, self.relative), self.leaf)

    def test_only_actual_enoent_is_absence(self):
        self.assertIsNone(physical.optional_lstat(self.root / "absent"))
        for number in (errno.EACCES, errno.EIO, errno.ENOTDIR):
            with self.subTest(errno=number), patch.object(Path, "lstat", side_effect=OSError(number, "fixture fault")):
                with self.assertRaises(OSError) as caught:
                    physical.optional_lstat(self.root / ".git")
                self.assertEqual(caught.exception.errno, number)

    def test_each_enclosing_marker_type_rejected_then_restored(self):
        for parent in (self.root / "test", self.leaf.parent):
            for kind in ("file", "directory", "dangling-symlink"):
                with self.subTest(parent=parent, kind=kind):
                    marker = parent / ".git"
                    if kind == "file":
                        marker.write_bytes(b"gitdir: anywhere")
                    elif kind == "directory":
                        marker.mkdir()
                    else:
                        marker.symlink_to(parent / "nonexistent")
                    with self.assertRaisesRegex(ValueError, "Nested Git"):
                        physical.regular_file(self.root, self.relative)
                    if kind == "directory":
                        marker.rmdir()
                    else:
                        marker.unlink()
                    self.assertEqual(physical.regular_file(self.root, self.relative).read_bytes(), b"selected bytes")

    def test_each_enclosing_search_only_directory_rejected_then_restored(self):
        for directory in (self.root / "test", self.leaf.parent):
            with self.subTest(directory=directory):
                directory.chmod(0o111)
                try:
                    with self.assertRaisesRegex(ValueError, "Inaccessible"):
                        physical.regular_file(self.root, self.relative)
                finally:
                    directory.chmod(0o755)
                self.assertEqual(physical.regular_file(self.root, self.relative).read_bytes(), b"selected bytes")

    def test_leaf_link_empty_directory_fifo_fail_without_reading(self):
        original = self.leaf.read_bytes()
        for kind in ("symlink", "empty", "directory", "fifo"):
            with self.subTest(kind=kind):
                self.leaf.unlink()
                if kind == "symlink":
                    self.leaf.symlink_to(self.root / "nonexistent")
                elif kind == "empty":
                    self.leaf.write_bytes(b"")
                elif kind == "directory":
                    self.leaf.mkdir()
                else:
                    os.mkfifo(self.leaf)
                with self.assertRaises(ValueError):
                    physical.regular_file(self.root, self.relative)
                if kind == "directory":
                    self.leaf.rmdir()
                else:
                    self.leaf.unlink()
                self.leaf.write_bytes(original)
                self.assertEqual(physical.regular_file(self.root, self.relative).read_bytes(), original)

    def test_lexical_escape_and_enotdir_not_treated_as_missing(self):
        for relative in (Path("../leaf"), self.leaf):
            with self.assertRaises(ValueError):
                physical.regular_file(self.root, relative)
        with self.assertRaises(NotADirectoryError):
            physical.optional_lstat(self.leaf / ".git")


if __name__ == "__main__":
    unittest.main()
