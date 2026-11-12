import sys

sys.dont_write_bytecode = True

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
import unittest

from tests.git_fixture import policy
from tests.helper_support import ROOT, original
from tests.test_publication import PublicationFixture


BUILD = "build macOS (universal)"
FINAL = "create-only final publication"


def extracted(name):
    lines = (ROOT / ".github/workflows/release.yml").read_text().splitlines()
    start = lines.index("      - name: " + name)
    run = next(i for i in range(start + 1, len(lines)) if lines[i] == "        run: |")
    body = []
    for line in lines[run + 1:]:
        if line and not line.startswith("          "):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"


class WorkflowPhaseTests(PublicationFixture, unittest.TestCase):
    def setUp(self):
        self.bash = shutil.which("bash")
        super().setUp()
        bin_path = self.root / ".git/fixture-bin"
        self.fixture.env["GIT_EXEC_PATH"] = self.fixture.git("--exec-path").decode().strip()
        for name, executable in (
            ("python3", sys.executable), ("git", shutil.which("git")),
            *((name, shutil.which(name)) for name in ("grep", "head", "sed")),
        ):
            (bin_path / name).symlink_to(executable)
        stub = self.root / ".git/native-stub.py"
        stub.write_bytes(("#!" + sys.executable + "\n").encode() +
                         (Path(__file__).parent / "native_stub.py").read_bytes())
        stub.chmod(0o755)
        for name in ("xcodebuild", "lipo", "security", "base64", "codesign", "ditto", "hdiutil", "xcrun"):
            (bin_path / name).symlink_to(stub)
        self.fixture.env.update(
            PATH=str(bin_path), GITHUB_SHA=self.fixture.sha, GITHUB_REF="refs/heads/master",
            PRODUCT_NAME="ImageCaptureCore", XCODE_PROJECT="ImageCaptureCore.xcodeproj",
            MACOS_DEPLOYMENT_TARGET="11.0", VERSION="2.1.6", EXPECTED_VERSION="2.1.6",
            GITHUB_ENV=str(self.root / ".git/workflow-env"),
            GITHUB_OUTPUT=str(self.root / ".git/workflow-output"),
            RUNNER_TEMP=str(self.root / ".git/runner"),
            CERT_BASE64="offline-not-a-certificate", CERT_PASSWORD="offline-dummy",
            KEYCHAIN_PASSWORD="offline-dummy", APPLE_ID="offline@example.invalid",
            TEAM_ID="OFFLINE", APP_PASSWORD="offline-dummy",
        )
        for name in ("BASH_ENV", "ENV", "PYTHONPATH", "PYTHONHOME"):
            self.fixture.env.pop(name, None)
        (self.root / ".git/runner").mkdir()
        self.native_state_path = self.root / ".git/native-state.json"
        self.reset_native()

    def reset_native(self, mode="positive"):
        self.native_state_path.write_text(json.dumps({"mode": mode, "calls": []}))

    def native_state(self):
        return json.loads(self.native_state_path.read_text())

    def phase(self, name):
        result = subprocess.run(
            [self.bash, "--noprofile", "--norc", "-c", extracted(name)],
            cwd=self.root, env=self.fixture.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        environment = Path(self.fixture.env["GITHUB_ENV"])
        if environment.exists():
            for line in environment.read_text().splitlines():
                key, value = line.split("=", 1)
                self.assertIn(key, ("KEYCHAIN_PATH", "BUNDLE_PATH"))
                self.fixture.env[key] = value
        return result

    def good(self, name):
        result = self.phase(name)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        return result

    def final_positive(self):
        before = self.fixture.snapshot()
        self.good(FINAL)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertFalse(list(self.root.rglob("__pycache__")))

    def reset_build_fixture(self):
        # Separate disposable test cases only; never used to fake a final publication.
        for directory in policy.DIRECTORY_TARGETS:
            path = self.root / directory
            if path.exists():
                shutil.rmtree(path)
        self.fixture.restore_selected()
        self.reset_api()
        self.reset_native()

    def seed_empty_intermediates(self):
        for directory in (
            *policy.DIRECTORY_TARGETS, policy.TARGET_TEMP + "/Objects-normal/arm64",
            policy.XC + "/" + "a"*32 + ".xcbuilddata/subdirectory",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)

    def negative_build(self):
        before = self.fixture.snapshot()
        for name in ("recheck source and availability before credentials", BUILD):
            result = self.phase(name)
            self.assertNotEqual(result.returncode, 0, name)
            self.assertEqual(self.fixture.snapshot(), before)
            self.assertEqual(self.native_state()["calls"], [], result.stderr.decode())
            self.assertEqual(self.state()["calls"], [], result.stderr.decode())

    def restored_build(self, original_snapshot):
        self.assertEqual(self.fixture.snapshot(), original_snapshot)
        preserved = {path: (self.root / path).read_bytes()
                     for path in (*policy.COPIED_RESOURCES, *policy.PRESERVED_LEAVES)}
        self.good(BUILD)
        self.assertEqual([call[0] for call in self.native_state()["calls"]], ["xcodebuild"])
        self.assertEqual(self.state()["calls"], [])
        for path, data in preserved.items():
            self.assertEqual((self.root / path).read_bytes(), data)
        self.assertTrue(all((self.root / path).is_file() for path in policy.GENERATED_LEAVES))
        self.reset_build_fixture()

    def test_exact_workflow_surface_and_original_native_policy(self):
        bump = (ROOT / ".github/workflows/bump-version.yml").read_text()
        build = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertEqual(sorted(path.name for path in (ROOT / ".github/workflows").glob("*.yml")),
                         ["bump-version.yml", "ownership-regressions.yml", "release.yml"])
        ownership = (ROOT / ".github/workflows/ownership-regressions.yml").read_text()
        self.assertIn("\npermissions:\n  contents: read\n", ownership)
        self.assertIn("persist-credentials: false", ownership)
        self.assertNotIn("secrets.", ownership)
        self.assertNotRegex(ownership, r"workflow_dispatch|workflow_call|pull_request_target|release|tags")
        self.assertIn("run: tests/ownership/run.sh . fixed\n", ownership)
        self.assertTrue(build.startswith("name: Build\n\non:\n  workflow_dispatch:\n\n"))
        self.assertNotIn("inputs:", build)
        self.assertEqual(bump.count("type: choice"), 1)
        self.assertIn("options:\n          - patch\n          - minor\n          - major\n", bump)
        self.assertIn("default: patch\n        required: true", bump)
        for workflow in (bump, build):
            self.assertIn("group: ica-publication\n  cancel-in-progress: false", workflow)
            for match in re.finditer(r"uses: actions/checkout@[^\n]+\n", workflow):
                tail = workflow[match.end():]
                self.assertTrue(tail.startswith("        with:\n          ref: ${{ github.sha }}"))
            self.assertNotRegex(workflow, r"\n  (?:push|pull_request|workflow_call):")
        self.assertEqual(re.findall(r"^  ([a-z-]+):\n    (?:runs-on|name):", build, re.MULTILINE),
                         ["version", "build-macos"])
        self.assertNotIn("CODE_SIGNING_ALLOWED", build)
        self.assertNotIn("SYMROOT=", build)
        self.assertNotIn("Windows", build)
        expected = original("ImageCaptureCore.xcodeproj/project.pbxproj").replace(
            b"CURRENT_PROJECT_VERSION = 2.1.0;", b"CURRENT_PROJECT_VERSION = 2.1.6;",
        )
        # Live version may genuinely bump later; canonical rendering changes only version spans.
        from tests.git_fixture import source
        live = (ROOT / source.PROJECT).read_bytes()
        live_version = source.read(ROOT)
        fixture_data = source.source_data(self.root)
        fixture_data[source.PROJECT] = expected
        self.assertEqual(live, source.render_version(fixture_data, live_version)[source.PROJECT])

    def test_actual_all_extracted_phases_absent_bytecode_env_then_real_final_cli_retains_all(self):
        for name in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX"):
            self.assertNotIn(name, self.fixture.env)
        for name in (
            "source version and early publication availability",
            "recheck source and availability before credentials",
            "import Developer ID certificate", "store notarytool credentials",
            BUILD, "verify universal binary", "codesign", "package, notarize & staple",
        ):
            self.good(name)
        self.assertTrue((self.root / policy.BUILT_PLIST).read_bytes().startswith(b"bplist00"))
        self.assertTrue((self.root / policy.BUILT_ENGLISH).read_bytes().startswith(b"bplist00"))
        self.assertNotEqual((self.root / policy.EXECUTABLE).read_bytes(),
                            self.fixture.git("show", "HEAD:" + policy.EXECUTABLE))
        self.reset_api()
        self.final_positive()
        calls = self.native_state()["calls"]
        self.assertEqual(sum(call[:3] == ["xcrun", "notarytool", "submit"] for call in calls), 2)
        self.assertIn(["xcrun", "stapler", "staple", "ImageCaptureCore-2.1.6.dmg"], calls)
        self.assertIn(["xcrun", "stapler", "validate", "ImageCaptureCore-2.1.6.dmg"], calls)
        self.assertGreaterEqual(sum(call[0] == "codesign" and "--strict" in call for call in calls), 2)
        self.assertTrue((self.root / "ImageCaptureCore-2.1.6.dmg").read_bytes().endswith(b"staple retained"))

    def test_each_ancestor_marker_access_and_write_fault_atomic_then_same_fixture_positive(self):
        parents = (
            "test", "test/Plugins", policy.BUNDLE, policy.CONTENTS,
            policy.CONTENTS + "/MacOS", policy.CONTENTS + "/Resources",
            policy.CONTENTS + "/Resources/English.lproj", policy.CONTENTS + "/_CodeSignature",
            policy.PROJECT_TEMP, policy.PROJECT_TEMP + "/Default", policy.TARGET_TEMP,
            policy.TARGET_TEMP + "/Objects-normal", policy.TARGET_TEMP + "/Objects-normal/arm64",
            policy.XC, policy.XC + "/" + "a"*32 + ".xcbuilddata",
            policy.XC + "/" + "a"*32 + ".xcbuilddata/subdirectory",
        )
        for parent in parents:
            for kind in ("marker-file", "marker-directory", "marker-link", "search-only", "no-search", "no-access"):
                with self.subTest(parent=parent, kind=kind):
                    self.seed_empty_intermediates()
                    original_snapshot = self.fixture.snapshot()
                    path = self.root / parent
                    marker = path / ".git"
                    mode = path.stat().st_mode & 0o777
                    if kind == "marker-file":
                        marker.write_bytes(b"gitdir: forbidden fixture marker")
                    elif kind == "marker-directory":
                        marker.mkdir()
                    elif kind == "marker-link":
                        marker.symlink_to(self.root / ".git")
                    else:
                        path.chmod({"search-only": 0o111, "no-search": 0o444, "no-access": 0}[kind])
                    try:
                        self.negative_build()
                    finally:
                        if kind == "marker-directory":
                            marker.rmdir()
                        elif kind.startswith("marker-"):
                            marker.unlink()
                        else:
                            path.chmod(mode)
                    self.restored_build(original_snapshot)
        for parent in ("test/Plugins", policy.CONTENTS, policy.CONTENTS + "/MacOS",
                       policy.CONTENTS + "/Resources/English.lproj", policy.CONTENTS + "/_CodeSignature"):
            with self.subTest(delete_parent=parent):
                self.seed_empty_intermediates()
                before = self.fixture.snapshot()
                path = self.root / parent
                mode = path.stat().st_mode & 0o777
                path.chmod(0o555)
                try:
                    self.negative_build()
                finally:
                    path.chmod(mode)
                self.restored_build(before)

    def test_each_typed_target_and_symlink_ancestor_atomic_then_same_fixture_positive(self):
        for target in (*sorted(policy.GENERATED_LEAVES), *policy.DIRECTORY_TARGETS):
            for kind in ("wrongtype", "samebytes-symlink", "fifo"):
                with self.subTest(target=target, kind=kind):
                    self.seed_empty_intermediates()
                    before = self.fixture.snapshot()
                    path = self.root / target
                    backup = self.root / ".git/target-backup"
                    path.rename(backup)
                    if kind == "wrongtype":
                        if backup.is_dir():
                            path.write_bytes(b"wrong file for typed directory")
                        else:
                            path.mkdir()
                    elif kind == "samebytes-symlink":
                        path.symlink_to(backup)
                    else:
                        os.mkfifo(path)
                    try:
                        self.negative_build()
                    finally:
                        if path.is_dir() and not path.is_symlink():
                            path.rmdir()
                        else:
                            path.unlink()
                        backup.rename(path)
                    self.restored_build(before)
        for parent in ("test", "test/Plugins", policy.BUNDLE, policy.CONTENTS,
                       policy.CONTENTS + "/Resources", policy.TARGET_TEMP + "/Objects-normal"):
            with self.subTest(symlink_ancestor=parent):
                self.seed_empty_intermediates()
                before = self.fixture.snapshot()
                path = self.root / parent
                backup = self.root / ".git/ancestor-backup"
                path.rename(backup)
                path.symlink_to(backup)
                try:
                    self.negative_build()
                finally:
                    path.unlink()
                    backup.rename(path)
                self.restored_build(before)

    def test_each_os_errno_access_and_unreadable_leaf_atomic_then_same_fixture_positive(self):
        interpreter = self.root / ".git/fixture-bin/python3"
        wrapper = ("#!" + sys.executable + "\n").encode() + (
            Path(__file__).parent / "python_fault_wrapper.py").read_bytes()
        for kind in ("EACCES", "EIO", "ENOTDIR", "access-false"):
            with self.subTest(fault=kind):
                before = self.fixture.snapshot()
                interpreter.unlink()
                interpreter.write_bytes(wrapper)
                interpreter.chmod(0o755)
                self.fixture.env.update(
                    FIXTURE_FAULT_KIND=kind,
                    FIXTURE_FAULT_PATH=(policy.CONTENTS + "/_CodeSignature" +
                                        ("/.git" if kind != "access-false" else "")),
                )
                try:
                    self.negative_build()
                finally:
                    interpreter.unlink()
                    interpreter.symlink_to(sys.executable)
                    self.fixture.env.pop("FIXTURE_FAULT_KIND")
                    self.fixture.env.pop("FIXTURE_FAULT_PATH")
                self.restored_build(before)
        for leaf in sorted(policy.GENERATED_LEAVES):
            with self.subTest(unreadable_leaf=leaf):
                before = self.fixture.snapshot()
                path = self.root / leaf
                mode = path.stat().st_mode & 0o777
                path.chmod(0)
                try:
                    self.negative_build()
                finally:
                    path.chmod(mode)
                self.restored_build(before)

    def test_actual_initial_ignored_db_rejected_then_fresh_db_retained(self):
        path = self.fixture.write("test/Plugins/XCBuildData/build.db", b"preexisting ignored DB")
        (self.root / ".git/info/exclude").write_text("test/Plugins/XCBuildData/\n")
        self.assertEqual(self.fixture.git("status", "--porcelain"), b"")
        self.negative_build()
        self.reset_api()
        before = self.fixture.snapshot()
        result = self.phase("recheck source and availability before credentials")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state()["calls"], [])
        self.assertEqual(self.native_state()["calls"], [])
        self.assertEqual(self.fixture.snapshot(), before)
        path.unlink()
        self.good("recheck source and availability before credentials")
        self.good(BUILD)
        self.fixture.env.update(BUNDLE_PATH="test/Plugins/ImageCaptureCore.bundle",
                                KEYCHAIN_PATH=str(self.root / ".git/runner/build.keychain-db"))
        self.good("verify universal binary")
        self.good("codesign")
        self.good("package, notarize & staple")
        self.reset_api()
        self.final_positive()
        self.assertEqual(path.read_bytes(), b"fresh native DB retained")

    def test_exact_architecture_tokens_extras_allowed_each_negative_then_positive(self):
        self.good(BUILD)
        for bad in ("arm64e x86_64", "arm64 x86_64h", "arm64", "x86_64"):
            with self.subTest(tokens=bad):
                self.reset_native()
                self.fixture.env["FIXTURE_ARCHS"] = bad
                before = self.fixture.snapshot()
                result = self.phase("verify universal binary")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.fixture.snapshot(), before)
                self.assertEqual(self.state()["calls"], [])
                self.fixture.env["FIXTURE_ARCHS"] = "arm64 x86_64 i386 arm64e"
                self.good("verify universal binary")
                self.assertEqual(self.fixture.snapshot(), before)

    def test_both_notary_exit_and_strict_accepted_json_staple_and_strictsign(self):
        self.good(BUILD)
        self.fixture.env.update(BUNDLE_PATH="test/Plugins/ImageCaptureCore.bundle",
                                KEYCHAIN_PATH=str(self.root / ".git/runner/build.keychain-db"))
        for mode in (
            *(suffix + "-" + defect for suffix in ("zip", "dmg")
              for defect in ("exit", "rejected", "duplicate", "nonfinite", "overflow", "malformed", "schema")),
            "staple", "validate", "strict-signature",
        ):
            with self.subTest(mode=mode):
                self.reset_native(mode)
                before = self.fixture.snapshot()
                result = self.phase("package, notarize & staple")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.state()["calls"], [])
                self.assertEqual((self.root / policy.EXECUTABLE).read_bytes(),
                                 before[policy.EXECUTABLE][1])
                exclude = {"ImageCaptureCore-2.1.6.zip", "ImageCaptureCore-2.1.6.dmg"}
                self.assertEqual(
                    {key: value for key, value in self.fixture.snapshot().items() if key not in exclude},
                    {key: value for key, value in before.items() if key not in exclude},
                )
                self.reset_native()
                self.good("package, notarize & staple")
                self.reset_api()
                self.final_positive()
                self.reset_api()
