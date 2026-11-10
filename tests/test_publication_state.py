import sys

sys.dont_write_bytecode = True

import json
import unittest

from tests.test_publication import PublicationFixture


ZIP = "ImageCaptureCore-2.1.6.zip"
DMG = "ImageCaptureCore-2.1.6.dmg"


class PublicationStateTests(PublicationFixture, unittest.TestCase):
    def failure(self, mode, *, posts, actual_assets, release_created):
        self.prepare()
        self.reset_api(mode)
        before, index = self.fixture.snapshot(), self.fixture.git("ls-files", "--stage", "-z")
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Publication stopped:", result.stderr)
        self.assertIn(b"retained", result.stderr)
        lines = result.stderr.decode().splitlines()
        reports = [line.removeprefix("Publication partial state: ") for line in lines
                   if line.startswith("Publication partial state: ")]
        self.assertEqual(len(reports), 1, result.stderr.decode())
        report = json.loads(reports[0])
        self.assertEqual(report["version"], "2.1.6")
        self.assertEqual(report["tag"], "v2.1.6")
        self.assertEqual(report["selected_sha"], self.fixture.sha)
        self.assertEqual(self.fixture.snapshot(), before)
        self.assertEqual(self.fixture.git("ls-files", "--stage", "-z"), index)
        self.assertEqual(
            self.fixture.git("ls-remote", "--refs", "origin", "refs/tags/v2.1.6").decode().strip(),
            self.fixture.sha + "\trefs/tags/v2.1.6",
        )
        state = self.state()
        self.assertTrue(state["ref_created"])
        self.assertEqual(state["release_created"], release_created)
        self.assertEqual(state["assets"], actual_assets)
        if release_created:
            self.assertEqual(state["created_release_id"], 101)
        calls = [(call["method"], call["endpoint"]) for call in state["calls"]]
        self.assertTrue(all(method in ("GET", "POST") for method, _ in calls))
        self.assertEqual(len(calls), len(set(calls)), "No retries or diagnostic API requests")
        self.assertEqual(sum(method == "POST" for method, _ in calls), posts)
        self.assertEqual(calls[:5], [
            ("GET", "repos/miyako/4d-plugin-ica"),
            ("GET", "repos/miyako/4d-plugin-ica/releases?per_page=100&page=1"),
            ("GET", "repos/miyako/4d-plugin-ica/releases?per_page=100&page=2"),
            ("GET", "repos/miyako/4d-plugin-ica/git/matching-refs/tags/v2.1.6"),
            ("POST", "repos/miyako/4d-plugin-ica/git/refs"),
        ])
        expected_tail = []
        if mode not in ("post-ref-lost-response", "post-ref-sha"):
            expected_tail.append(("GET", "repos/miyako/4d-plugin-ica/git/ref/tags/v2.1.6"))
        if release_created:
            expected_tail.append(("POST", "repos/miyako/4d-plugin-ica/releases"))
        if posts >= 3:
            expected_tail.append(("POST", "https://uploads.github.com/repos/miyako/4d-plugin-ica/releases/101/assets?name=" + ZIP))
        if posts == 4:
            expected_tail.append(("POST", "https://uploads.github.com/repos/miyako/4d-plugin-ica/releases/101/assets?name=" + DMG))
        self.assertEqual(calls[5:], expected_tail)
        self.assertNotIn("PYTHONDONTWRITEBYTECODE", self.fixture.env)
        self.assertFalse(list(self.root.rglob("__pycache__")))
        return report, result.stderr.decode()

    def test_ref_verification_failure_reports_confirmed_create_but_unverified_tag(self):
        report, error = self.failure("verify-ref-failure", posts=1, actual_assets=[], release_created=False)
        self.assertIn("offline fixture API failure", error)
        self.assertIn("returned non-zero exit status 1", error)
        self.assertTrue(report["tag_attempted"])
        self.assertTrue(report["tag_confirmed"])
        self.assertFalse(report["tag_verified"])
        self.assertEqual(report["tag_response"], "validated_create_response")
        self.assertFalse(report["release_attempted"])
        self.assertIsNone(report["release_id"])
        self.assertEqual(report["release_id_status"], "not_attempted")
        self.assertEqual(report["confirmed_uploaded_names"], [])
        self.assertIsNone(report["attempted_upload"])

    def test_tag_lost_or_invalid_response_never_claims_confirmation(self):
        for mode, status, error_text in (
            ("post-ref-lost-response", "unknown_or_lost_response", "offline lost response after creating tag"),
            ("post-ref-sha", "received_unvalidated", "Created tag ref does not identify the selected commit"),
        ):
            with self.subTest(mode=mode):
                report, error = self.failure(mode, posts=1, actual_assets=[], release_created=False)
                self.assertIn(error_text, error)
                self.assertTrue(report["tag_attempted"])
                self.assertFalse(report["tag_confirmed"])
                self.assertFalse(report["tag_verified"])
                self.assertEqual(report["tag_response"], status)
                self.assertFalse(report["release_attempted"])
                self.assertIsNone(report["release_id"])

    def test_release_creation_lost_or_malformed_id_stays_unknown(self):
        for mode, status, error_text in (
            ("post-release-failure", "unknown_or_lost_response", "offline fixture API failure"),
            ("release-lost-response", "unknown_or_lost_response", "offline lost response after creating release"),
            ("release-malformed-response", "unknown_or_lost_response", "Expecting property name"),
            ("release-missing-id", "unknown_invalid_or_missing_response_id", "New release response"),
            ("new-id-bool", "unknown_invalid_or_missing_response_id", "New release response"),
        ):
            with self.subTest(mode=mode):
                report, error = self.failure(mode, posts=2, actual_assets=[], release_created=True)
                self.assertIn(error_text, error)
                self.assertTrue(report["tag_confirmed"] and report["tag_verified"])
                self.assertTrue(report["release_attempted"])
                self.assertIsNone(report["release_id"], "Never infer server ID101 from fixture state or malformed/lost JSON")
                self.assertEqual(report["release_id_status"], status)
                self.assertFalse(report["release_confirmed"])
                self.assertEqual(report["confirmed_uploaded_names"], [])
                self.assertIsNone(report["attempted_upload"])

    def test_positive_response_id_is_reported_without_claiming_invalid_release_success(self):
        for mode, response_id in (("new-name", 101), ("reused-id", 7), ("new-upload-url", 101)):
            with self.subTest(mode=mode):
                report, error = self.failure(mode, posts=2, actual_assets=[], release_created=True)
                self.assertIn("Publication stopped:", error)
                self.assertTrue(report["release_attempted"])
                self.assertEqual(report["release_id"], response_id)
                self.assertEqual(report["release_id_status"], "provided_positive_response_id")
                self.assertFalse(report["release_confirmed"])
                self.assertEqual(report["confirmed_uploaded_names"], [])
                self.assertIsNone(report["attempted_upload"])

    def test_first_second_upload_failure_known_id_confirmed_names_and_uncertain_attempt(self):
        for ordinal, mode in (
            (1, "upload-1-failure"), (2, "upload-2-failure"),
            (1, "upload-1-lost-response"), (2, "upload-2-lost-response"),
            (1, "upload-1-malformed-response"), (2, "upload-2-malformed-response"),
            (1, "asset-size"),
        ):
            with self.subTest(mode=mode):
                previous = [] if ordinal == 1 else [ZIP]
                attempted = ZIP if ordinal == 1 else DMG
                actual_assets = previous if mode.endswith("-failure") else previous + [attempted]
                report, error = self.failure(
                    mode, posts=2 + ordinal, actual_assets=actual_assets, release_created=True,
                )
                if mode.endswith("-failure"):
                    self.assertIn("offline fixture API failure", error)
                elif mode.endswith("-lost-response"):
                    self.assertIn("offline lost response after uploading " + attempted, error)
                elif mode.endswith("-malformed-response"):
                    self.assertIn("Expecting value", error)
                else:
                    self.assertIn("New-release asset verification failed", error)
                self.assertTrue(report["tag_confirmed"] and report["tag_verified"])
                self.assertTrue(report["release_attempted"] and report["release_confirmed"])
                self.assertEqual(report["release_id"], 101)
                self.assertEqual(report["release_id_status"], "provided_positive_response_id")
                self.assertEqual(report["confirmed_uploaded_names"], previous)
                self.assertEqual(report["attempted_upload"], attempted)
                self.assertTrue(report["attempted_upload_may_have_succeeded"])
