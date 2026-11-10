import sys

sys.dont_write_bytecode = True

import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import unittest

from tests.helper_support import ROOT, SCRIPTS, fixture, helper, original


source = helper("source_version")


class SourceVersionTests(unittest.TestCase):
    def setUp(self):
        self.root = fixture(self)
        self.original = {path: original(path) for path in source.SOURCE_PATHS}
        self.base = dict(self.original)
        self.base[source.PROJECT] = self.base[source.PROJECT].replace(
            b"CURRENT_PROJECT_VERSION = 2.1.0;", b"CURRENT_PROJECT_VERSION = 2.1.6;"
        )
        self.base[source.LOCALIZED] = self.base[source.LOCALIZED].replace(b"2.1.1", b"2.1.6")
        self.restore()

    def restore(self):
        for path, data in self.base.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_symlink():
                target.unlink()
            target.write_bytes(data)
            target.chmod(0o644)

    def snapshot(self):
        return {
            path: (
                "link" if (self.root / path).is_symlink() else "file",
                os.readlink(self.root / path) if (self.root / path).is_symlink()
                else (self.root / path).read_bytes(),
                stat.S_IMODE((self.root / path).lstat().st_mode),
            )
            for path in source.SOURCE_PATHS
        }

    def cli(self, *args):
        env = dict(os.environ)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        env.pop("PYTHONPYCACHEPREFIX", None)
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "source_version.py"), *map(str, args)],
            cwd=self.root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def reject(self, path, data):
        (self.root / path).write_bytes(data)
        before = self.snapshot()
        with self.assertRaises((ValueError, OSError)):
            source.bump("patch", self.root)
        self.assertEqual(self.snapshot(), before)
        self.restore()
        self.assertEqual(source.read(self.root), "2.1.6")

    def test_immutable_intake_fixture_and_exact_authorized_repair(self):
        self.assertEqual(self.original[source.PROJECT].count(b"CURRENT_PROJECT_VERSION = 2.1.0;"), 6)
        self.assertEqual(self.original[source.PROJECT].count(b"MARKETING_VERSION = 2.1.6;"), 6)
        self.assertEqual(self.original[source.LOCALIZED].count(b"2.1.1"), 2)
        self.assertNotIn(b"\n", self.original[source.LOCALIZED])
        self.assertTrue(self.original[source.LOCALIZED].endswith(b"\r"))
        self.assertNotIn(source.BUILD, source.load_plist(self.original[source.PLIST]))
        for path, data in self.original.items():
            (self.root / path).write_bytes(data)
        with self.assertRaisesRegex(ValueError, "drift"):
            source.read(self.root)
        self.restore()
        self.assertEqual(source.read(self.root), "2.1.6")

    def test_live_source_expectation_is_dynamic(self):
        actual = source.read(ROOT)
        self.assertRegex(actual, f"^{source.VERSION}$")
        fields = source.project_settings(source.decode((ROOT / source.PROJECT).read_bytes())[0])
        self.assertEqual(source.resolve_settings(fields)["CURRENT_PROJECT_VERSION"], actual)

    def test_all_modes_exact_tokens_modes_and_optional_absence(self):
        for mode, expected in (("patch", "2.1.7"), ("minor", "2.2.0"), ("major", "3.0.0")):
            with self.subTest(mode=mode):
                self.restore()
                for path in source.SOURCE_PATHS:
                    (self.root / path).chmod(0o751)
                self.assertEqual(source.bump(mode, self.root), expected)
                for path, raw in self.base.items():
                    self.assertEqual((self.root / path).read_bytes(), raw.replace(b"2.1.6", expected.encode()))
                    self.assertEqual(stat.S_IMODE((self.root / path).stat().st_mode), 0o751)
                self.assertNotIn(source.BUILD, source.load_plist((self.root / source.PLIST).read_bytes()))

    def test_canonical_versions(self):
        for invalid in ("02.1.6", "2.01.6", "2.1.06", "2.1", "v2.1.6", "2.1.6-rc1", "2.1.6+build", "-1.0.0"):
            with self.subTest(invalid=invalid):
                self.reject(source.PROJECT, self.base[source.PROJECT].replace(b"2.1.6", invalid.encode()))

    def test_missing_extra_and_unpaired_version_assignments(self):
        data = self.base[source.PROJECT]
        for key in source.KEYS:
            assignment = f"{key} = 2.1.6;".encode()
            for changed in (
                data.replace(assignment, b"", 1),
                data.replace(assignment, assignment + b" " + assignment, 1),
                data.replace(assignment, assignment + b' "' + key.encode() + b'" = 2.1.6;', 1),
                data.replace(assignment, b"OTHER = unused; " + assignment + b" " + assignment, 1),
                data.replace(assignment, assignment.replace(b"2.1.6", b"2.1.5"), 1),
                data.replace(assignment, assignment.replace(b"2.1.6", b"(2.1.6)"), 1),
            ):
                with self.subTest(key=key, change=changed[:20]):
                    self.reject(source.PROJECT, changed)
        changed = data.replace(b"CURRENT_PROJECT_VERSION = 2.1.6;", b"", 1)
        changed = changed.replace(b"\tclasses = {", b"\tclasses = { CURRENT_PROJECT_VERSION = 2.1.6;", 1)
        self.reject(source.PROJECT, changed)

    def test_exact_configuration_identity_name_isa_and_scope(self):
        data = self.base[source.PROJECT]
        for changed in (
            data.replace(b"name = Development;", b"name = Renamed;", 1),
            data.replace(b"42D60B400A9DDBC8002ABB42", b"42D60B400A9DDBC8002ABB43"),
            data.replace(b"isa = XCBuildConfiguration;", b"isa = Other;", 1),
            data.replace(b"buildSettings = {", b"unrelated = {", 1),
            data.replace(b"isa = XCBuildConfiguration;", b"isa = XCBuildConfiguration; isa = XCBuildConfiguration;", 1),
        ):
            with self.subTest(change=changed[:20]):
                self.reject(source.PROJECT, changed)

    def test_inline_quoted_keys_comments_and_string_noise(self):
        value = self.base[source.PROJECT].decode()
        for key in source.KEYS:
            value = value.replace(f"{key} = ", f'"{key}" = ')
        value = value.replace("buildSettings = {", "buildSettings = { noise = \"MARKETING_VERSION = 9.9.9;\";", 1)
        value = value.removeprefix("// !$*UTF8*$!\n")
        value = re.sub(r"\s+", " ", value)
        value = "/* CURRENT_PROJECT_VERSION = 9.9.9; */\n// MARKETING_VERSION = 8.8.8;\n" + value
        (self.root / source.PROJECT).write_bytes(value.encode())
        self.assertEqual(source.bump("patch", self.root), "2.1.7")
        self.assertIn(b'MARKETING_VERSION = 9.9.9;', (self.root / source.PROJECT).read_bytes())

    def test_exact_target_product_fields_and_no_project_override(self):
        data = self.base[source.PROJECT]
        for key, value in source.PROJECT_PRODUCT_FIELDS.items():
            assignment = f"{key} = {value};".encode()
            for changed in (
                data.replace(assignment, assignment.replace(value.encode(), b"other"), 1),
                data.replace(assignment, b"", 1),
                data.replace(assignment, assignment + b" " + assignment, 1),
                data.replace(assignment, assignment + b' "' + key.encode() + b'" = "' + value.encode() + b'";', 1),
                data.replace(b"ARCHS = ", assignment + b" ARCHS = ", 1),
            ):
                with self.subTest(key=key):
                    self.reject(source.PROJECT, changed)

    def test_unterminated_or_unbalanced_project(self):
        for changed in (
            self.base[source.PROJECT] + b"/*",
            self.base[source.PROJECT] + b'"',
            self.base[source.PROJECT] + b"{",
            self.base[source.PROJECT] + b"}",
        ):
            self.reject(source.PROJECT, changed)

    def test_project_references_preserved_and_invalid_cycles_fail(self):
        data = self.base[source.PROJECT]
        for reference in (b"$(MARKETING_VERSION)", b"${MARKETING_VERSION}"):
            self.restore()
            (self.root / source.PROJECT).write_bytes(data.replace(
                b"CURRENT_PROJECT_VERSION = 2.1.6;", b"CURRENT_PROJECT_VERSION = " + reference + b";"
            ))
            self.assertEqual(source.bump("patch", self.root), "2.1.7")
            self.assertEqual((self.root / source.PROJECT).read_bytes().count(reference), 6)
        for reference in (b"$(UNDEFINED)", b"$(CURRENT_PROJECT_VERSION)"):
            self.reject(source.PROJECT, data.replace(
                b"CURRENT_PROJECT_VERSION = 2.1.6;", b"CURRENT_PROJECT_VERSION = " + reference + b";"
            ))
        self.reject(source.PROJECT, data.replace(
            b"CURRENT_PROJECT_VERSION = 2.1.6;", b"CURRENT_PROJECT_VERSION = $(MARKETING_VERSION);"
        ).replace(b"MARKETING_VERSION = 2.1.6;", b"MARKETING_VERSION = $(CURRENT_PROJECT_VERSION);"))

    def test_optional_build_and_plist_localization_references(self):
        for reference in ("$(MARKETING_VERSION)", "${CURRENT_PROJECT_VERSION}", "2.1.6"):
            with self.subTest(reference=reference):
                self.restore()
                raw = self.base[source.PLIST].replace(b"<string>2.1.6</string>", f"<string>{reference}</string>".encode())
                raw = raw.replace(b"</dict>", f"<key>CFBundleVersion</key><string>{reference}</string></dict>".encode())
                (self.root / source.PLIST).write_bytes(raw)
                localized = self.base[source.LOCALIZED].replace(
                    b'CFBundleShortVersionString = "2.1.6";',
                    f'CFBundleShortVersionString = "{reference}"; CFBundleVersion = "{reference}";'.encode(),
                )
                (self.root / source.LOCALIZED).write_bytes(localized)
                self.assertEqual(source.bump("minor", self.root), "2.2.0")
                if reference.startswith("$"):
                    self.assertEqual((self.root / source.PLIST).read_bytes(), raw)
                    self.assertIn(reference.encode(), (self.root / source.LOCALIZED).read_bytes())
                else:
                    self.assertNotIn(b"2.1.6", (self.root / source.PLIST).read_bytes())

    def test_plist_duplicates_missing_invalid_types_refs_and_product(self):
        data = self.base[source.PLIST]
        for changed in (
            data.replace(b"<key>CFBundleShortVersionString</key>", b"<key>Missing</key>"),
            data.replace(b"<string>2.1.6</string>", b"<integer>216</integer>"),
            data.replace(b"<string>2.1.6</string>", b"<string>$(UNKNOWN)</string>"),
            data.replace(b"</dict>", b"<key>CFBundleShortVersionString</key><string>2.1.6</string></dict>"),
            data.replace(b"</dict>", b"<key>CFBundleVersion</key><string>2.1.5</string></dict>"),
            data.replace(b"com.4D.ImageCaptureCore", b"com.4D.other"),
            data.replace(b"<string>ImageCaptureCore</string>", b"<string>other</string>"),
            b"garbage", plistlib.dumps(["not", "dictionary"]),
        ):
            self.reject(source.PLIST, changed)

    def test_localization_duplicates_drift_name_copyright_and_invalid_encoding(self):
        data = self.base[source.LOCALIZED]
        for changed in (
            data.replace(b"2.1.6", b"2.1.5", 1),
            data.replace(b"version 2.1.6", b"version 2.1.5"),
            data.replace(b"Copyright 2025", b"Copyright 2021"),
            data.replace(b'CFBundleName = "ImageCaptureCore";', b'CFBundleName = "other";'),
            data + b' CFBundleShortVersionString = "2.1.6";',
            data + b' "CFBundleShortVersionString" = "2.1.6";',
            data + b' other = "value"; CFBundleGetInfoString = "duplicate";',
            data.replace(b"CFBundleShortVersionString", b"Missing"),
            data + b"\x00", data + b"\xff",
        ):
            self.reject(source.LOCALIZED, changed)

    def test_encodings_boms_bomless_and_per_line_endings(self):
        for encoding, bom in (
            ("utf-8", b""), ("utf-8", b"\xef\xbb\xbf"),
            ("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff"),
            ("utf-16-le", b""), ("utf-16-be", b""),
        ):
            for endings in (("\n",), ("\r",), ("\r\n",), ("\r", "\n", "\r\n")):
                with self.subTest(encoding=encoding, bom=bom, endings=endings):
                    self.restore()
                    before = {}
                    for path, raw in self.base.items():
                        text = raw.decode()
                        if path == source.PLIST and encoding.startswith("utf-16"):
                            text = text.replace('encoding="UTF-8"', 'encoding="UTF-16"')
                        lines = text.splitlines()
                        text = "".join(line + endings[index % len(endings)] for index, line in enumerate(lines))
                        if not raw.endswith((b"\r", b"\n")):
                            text = text[:-len(endings[(len(lines) - 1) % len(endings)])]
                        before[path] = bom + text.encode(encoding)
                        (self.root / path).write_bytes(before[path])
                    self.assertEqual(source.bump("patch", self.root), "2.1.7")
                    for path, raw in before.items():
                        old_text, codec, actual_bom = source.decode(raw)
                        self.assertEqual((self.root / path).read_bytes(),
                                         actual_bom + old_text.replace("2.1.6", "2.1.7").encode(codec))

    def test_late_missing_or_unwritable_source_before_any_write(self):
        target = self.root / source.LOCALIZED
        target.unlink()
        first = (self.root / source.PROJECT).read_bytes()
        with self.assertRaises(OSError):
            source.bump("patch", self.root)
        self.assertEqual((self.root / source.PROJECT).read_bytes(), first)
        self.restore()
        target.chmod(0o444)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Unwritable"):
            source.bump("patch", self.root)
        self.assertEqual(self.snapshot(), before)
        target.chmod(0o644)
        self.assertEqual(source.bump("patch", self.root), "2.1.7")

    def test_samebytes_symlink_and_enclosing_git_marker(self):
        target = self.root / source.LOCALIZED
        alternate = self.root / "original.strings"
        alternate.write_bytes(target.read_bytes())
        target.unlink()
        target.symlink_to(alternate)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "regular file"):
            source.bump("patch", self.root)
        self.assertEqual(self.snapshot(), before)
        self.restore()
        marker = target.parent / ".git"
        marker.write_bytes(b"not a repository")
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, "Nested Git"):
            source.bump("patch", self.root)
        self.assertEqual(self.snapshot(), before)
        marker.unlink()
        self.assertEqual(source.bump("patch", self.root), "2.1.7")

    def bundle(self, fmt):
        bundle = self.root / "test/Plugins/ImageCaptureCore.bundle"
        plist = bundle / "Contents/Info.plist"
        localized = bundle / "Contents/Resources" / source.LOCALIZED
        plist.parent.mkdir(parents=True, exist_ok=True)
        localized.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(plistlib.dumps(source.load_plist(self.base[source.PLIST]), fmt=fmt))
        fields = {key: field[0] for key, field in source.localized_fields(self.base[source.LOCALIZED].decode()).items()}
        localized.write_bytes(plistlib.dumps(fields, fmt=fmt))
        return bundle, plist, localized

    def test_built_xml_binary_and_actual_localization_dictionary(self):
        for fmt in (plistlib.FMT_XML, plistlib.FMT_BINARY):
            self.restore()
            bundle, plist, localized = self.bundle(fmt)
            before = (plist.read_bytes(), localized.read_bytes())
            source.verify_bundle(bundle, self.root)
            self.assertEqual((plist.read_bytes(), localized.read_bytes()), before)
            localized.write_bytes(b"\xff\xfe" + self.base[source.LOCALIZED].decode().encode("utf-16-le"))
            source.verify_bundle(bundle, self.root)

    def test_built_short_build_product_and_localization_negatives_restored(self):
        bundle, plist, localized = self.bundle(plistlib.FMT_BINARY)
        baseline = (plist.read_bytes(), localized.read_bytes())
        for key, value in (
            (source.SHORT, "2.1.5"), (source.BUILD, "2.1.6"),
            ("CFBundleIdentifier", "wrong"), ("CFBundleExecutable", "wrong"),
        ):
            with self.subTest(key=key):
                data = dict(source.load_plist(baseline[0]))
                data[key] = value
                plist.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY))
                with self.assertRaises(ValueError):
                    source.verify_bundle(bundle, self.root)
                plist.write_bytes(baseline[0])
                source.verify_bundle(bundle, self.root)
        for key in ("CFBundleName", source.SHORT, source.INFO, source.BUILD):
            with self.subTest(localized_key=key):
                data = dict(source.load_plist(baseline[1]))
                data[key] = "wrong"
                localized.write_bytes(plistlib.dumps(data, fmt=plistlib.FMT_BINARY))
                with self.assertRaises(ValueError):
                    source.verify_bundle(bundle, self.root)
                localized.write_bytes(baseline[1])
                source.verify_bundle(bundle, self.root)

    def test_actual_cli_absent_bytecode_env_no_B_and_readonly_bundle_retention(self):
        bundle, plist, localized = self.bundle(plistlib.FMT_BINARY)
        before = self.snapshot(), plist.read_bytes(), localized.read_bytes()
        result = self.cli("--verify-bundle", bundle)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.snapshot(), plist.read_bytes(), localized.read_bytes()), before)
        result = self.cli("--bump", "patch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), b"2.1.7")
        self.assertFalse(list(self.root.rglob("__pycache__")))
        self.assertFalse(list(SCRIPTS.rglob("__pycache__")))

    def test_actual_cli_negative_then_samefixture_restored_positive(self):
        (self.root / source.LOCALIZED).write_bytes(self.base[source.LOCALIZED] + b' CFBundleShortVersionString = "2.1.6";')
        before = self.snapshot()
        result = self.cli("--bump", "patch")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)
        self.restore()
        result = self.cli("--bump", "patch")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), b"2.1.7")


if __name__ == "__main__":
    unittest.main()
