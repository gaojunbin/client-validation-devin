"""Cross-platform root-cause grouping, archive unpacking and the merged branch report."""

import contextlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import helpers
from client_validation_devin import cli
from client_validation_devin.archives import unpack
from client_validation_devin.errors import QaError
from client_validation_devin.verdict import same_root, shared_root_causes
from fake_devin import FakeDevin


def issue(category, title, location="", scenario=""):
    return {"id": title[:6], "severity": "minor", "category": category, "title": title,
            "suspected_location": location, "scenario": scenario}


class RootCauseTest(unittest.TestCase):
    def test_shared_source_file_groups_differently_worded_issues(self):
        mac = issue("test", "Installer unit tests depend on a directory created by another suite",
                    "tests/update-installer.test.ts:44-45 setup()")
        win = issue("test", "Unit tests depend on another test creating .local/tests",
                    "tests/update-installer.test.ts:45 setup(); tests/update-checker.test.ts:22")
        self.assertTrue(same_root(mac, win))

    def test_same_scenario_groups(self):
        a = issue("logic", "Setup misidentifies the fallback shortcut as Fn", scenario="setup-guide")
        b = issue("logic", "Setup guide mislabels detected fallback chord as Right Alt", scenario="setup-guide")
        self.assertTrue(same_root(a, b))

    def test_unrelated_issues_without_place_stay_apart(self):
        a = issue("test", "Lint error in billing", "app/src/main/java/a/Billing.kt:3")
        b = issue("test", "Swift build times out", "ios/Sources/App/Home.swift:9")
        self.assertFalse(same_root(a, b))
        self.assertFalse(same_root(issue("layout", "Clipped title"), issue("visual", "Clipped title")))

    def test_groups_need_two_platforms(self):
        a = issue("logic", "Wrong label", scenario="s")
        self.assertEqual(shared_root_causes({"macos": [a, dict(a, id="x")]}), [])
        self.assertEqual(len(shared_root_causes({"macos": [a], "windows": [dict(a)]})), 1)


class UnpackTest(unittest.TestCase):
    def test_unpacks_and_refuses_escaping_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "r1-ios__layout__x__01.zip"
            with zipfile.ZipFile(good, "w") as z:
                z.writestr("shots/a.png", b"png")
            folder, count = unpack(good)
            self.assertEqual(count, 1)
            self.assertTrue((folder / "shots" / "a.png").is_file())
            evil = Path(tmp) / "evil.zip"
            with zipfile.ZipFile(evil, "w") as z:
                z.writestr("../../outside.txt", b"x")
            with self.assertRaises(QaError):
                unpack(evil)
            self.assertFalse((Path(tmp).parent / "outside.txt").exists())


class BranchReportTest(unittest.TestCase):
    def test_merges_the_latest_result_of_each_platform(self):
        repo = helpers.ProductRepo()
        clock = helpers.FakeClock()
        try:
            with FakeDevin({"ios": "pass", "android": "fail"}) as fake:
                env = {**helpers.clean_env(), **repo.env(fake.base)}
                out = io.StringIO()
                with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", clock.time), \
                        mock.patch("time.sleep", clock.sleep), contextlib.redirect_stdout(out), \
                        contextlib.redirect_stderr(io.StringIO()):
                    for platform in ("ios", "android"):
                        cli.main(["-C", str(repo.path), "run", "--platforms", platform])
                        cli.main(["-C", str(repo.path), "wait", "--timeout", "5000"])
                    out.truncate(0)
                    code = cli.main(["-C", str(repo.path), "report", "--branch"])
                text = out.getvalue()
                self.assertEqual(code, 1)
                self.assertIn("| ios | pass |", text)
                self.assertIn("| android | fail |", text)
                self.assertIn("Validated commit", text)
        finally:
            repo.cleanup()


if __name__ == "__main__":
    unittest.main()
