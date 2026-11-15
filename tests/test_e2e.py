"""End-to-end rounds against the fake Devin API: fail, fix, re-run, regression pass, release gate."""

import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

import helpers
from client_validation_devin import cli
from fake_devin import FakeDevin


class E2E(unittest.TestCase):
    def setUp(self):
        self.repo = helpers.ProductRepo()
        self.clock = helpers.FakeClock()

    def tearDown(self):
        self.repo.cleanup()

    def cli(self, fake: FakeDevin, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        env = {**helpers.clean_env(), **self.repo.env(fake.base)}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch("time.time", self.clock.time), mock.patch("time.sleep", self.clock.sleep), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["-C", str(self.repo.path), *args])
        return code, out.getvalue()

    def latest_report(self) -> dict:
        base = next(self.repo.state.glob("acme__notes/feature-x"))
        run_id = (base / "latest").read_text().strip()
        return json.loads((base / "runs" / run_id / "report.json").read_text())

    def test_fail_fix_rerun_regression_release(self):
        with FakeDevin({"ios": "pass", "android": "fail", "macos": "ask"}) as fake:
            code, out = self.cli(fake, "run", "--focus", "Editor toolbar changed")
            self.assertEqual(code, 3, out)
            self.assertIn("client-validation-devin wait", out)
            pushed = helpers.git(self.repo.remote, "rev-parse", "refs/heads/client-validation-devin/feature-x")
            self.assertEqual(pushed, helpers.git(self.repo.path, "rev-parse", "HEAD"))
            platforms_sent = sorted(b["platform"] for b in fake.created_bodies)
            self.assertEqual(platforms_sent, ["default", "macos", "macos"])  # linux fell back to default
            self.assertTrue(all(b["structured_output_required"] for b in fake.created_bodies))

            code, out = self.cli(fake, "wait", "--timeout", "5000")
            self.assertEqual(code, 1, out)
            report = self.latest_report()
            self.assertEqual({p: v["verdict"] for p, v in report["platforms"].items()},
                             {"ios": "pass", "android": "fail", "macos": "pass"})
            issue = report["platforms"]["android"]["gating"][0]
            self.assertEqual(issue["id"], "android-001")
            self.assertTrue(Path(issue["evidence_paths"][0]).is_file())
            self.assertEqual(report["platforms"]["android"]["errors"], [])
            self.assertTrue(report["platforms"]["android"]["not_downloaded"])
            macos_messages = [m["message"] for s in fake.sessions.values() if s["platform"] == "macos"
                              for m in s["messages"]]
            self.assertTrue(any(m.startswith("No human is available") for m in macos_messages))

            fake.behaviours["android"] = "pass"
            self.repo.commit_file("lib/editor/toolbar.dart", "fixed")
            code, out = self.cli(fake, "run", "--rerun")
            self.assertEqual(code, 3, out)
            self.assertEqual(len(fake.created_bodies), 3, "android session must be reused, not recreated")
            round_message = [m["message"] for s in fake.sessions.values() if s["platform"] == "android"
                             for m in s["messages"] if m["message"].startswith("NEW ROUND")][0]
            self.assertIn("Editor toolbar changed", round_message, "--rerun keeps the previous focus")
            code, out = self.cli(fake, "wait", "--timeout", "5000")
            self.assertEqual(code, 0, out)
            report = self.latest_report()
            self.assertIn("regression pass", report["next"])
            names = [v["name"] for v in report["platforms"]["android"]["not_downloaded"]]
            archive = "r2-android__launch__complete-evidence_light_en_std__01.zip"
            self.assertEqual(names, [archive, "r2-walkthrough.mp4"])
            self.assertEqual(report["platforms"]["android"]["fixed_issue_ids"], [])

            code, out = self.cli(fake, "release")
            self.assertEqual(code, 2, out)
            self.assertIn("NOT READY", out)

            code, out = self.cli(fake, "run", "--rerun")
            self.assertEqual(code, 3, out)
            code, out = self.cli(fake, "wait", "--timeout", "5000")
            self.assertEqual(code, 0, out)
            self.assertIn("client-validation-devin release", self.latest_report()["next"])

            code, out = self.cli(fake, "run", "--rerun")
            self.assertEqual(code, 0, out)
            self.assertIn("Nothing to run", out)
            code, out = self.cli(fake, "release")
            self.assertEqual(code, 0, out)
            self.assertIn("READY", out)

    def test_issue_that_survives_two_fix_rounds_needs_a_human(self):
        with FakeDevin({"android": "fail"}) as fake:
            for attempt in range(3):
                code, out = self.cli(fake, "run", "--platforms", "android")
                self.assertEqual(code, 3, out)
                code, out = self.cli(fake, "wait", "--timeout", "5000")
                self.repo.commit_file("lib/editor/toolbar.dart", f"attempt {attempt}")
            self.assertEqual(code, 5, out)
            self.assertIn("survived 2 fix rounds", " ".join(self.latest_report()["needs_human"]))

    def test_quota_suspension_needs_a_human(self):
        with FakeDevin({"ios": "quota"}) as fake:
            self.cli(fake, "run", "--platforms", "ios")
            code, out = self.cli(fake, "wait", "--timeout", "5000")
            self.assertEqual(code, 5, out)
            self.assertEqual(self.latest_report()["platforms"]["ios"]["verdict"], "blocked")

    def test_silent_session_is_nudged_then_reports(self):
        with FakeDevin({"ios": "silent"}) as fake:
            self.cli(fake, "run", "--platforms", "ios")
            code, out = self.cli(fake, "wait", "--timeout", "5000")
            self.assertEqual(code, 0, out)
            messages = [m["message"] for s in fake.sessions.values() for m in s["messages"]]
            self.assertTrue(any(m.startswith("Your turn ended") for m in messages))

    def test_wait_times_out_with_exit_3(self):
        with FakeDevin({"ios": "pass"}, polls_before_report=1000) as fake:
            self.cli(fake, "run", "--platforms", "ios")
            code, out = self.cli(fake, "wait", "--timeout", "30")
            self.assertEqual(code, 3, out)
            self.assertIn("Still running", out)

    def test_max_parallel_queues_platforms(self):
        qa = self.repo.path / ".devin" / "qa.toml"
        self.repo.commit_file(".devin/qa.toml", qa.read_text().replace(
            "reuse_sessions = true", "reuse_sessions = true\nmax_parallel = 1"))
        with FakeDevin({"ios": "pass", "android": "pass", "macos": "pass"}) as fake:
            code, out = self.cli(fake, "run")
            self.assertEqual(code, 3, out)
            self.assertEqual(len(fake.created_bodies), 1)
            self.assertEqual(out.count(": pending"), 2)
            code, out = self.cli(fake, "wait", "--timeout", "5000")
            self.assertEqual(code, 0, out)
            self.assertEqual(len(fake.created_bodies), 3)

    def test_parallel_runs_keep_their_own_results(self):
        with FakeDevin({"ios": "pass", "android": "fail"}, polls_before_report=4) as fake:
            code, out = self.cli(fake, "run", "--platforms", "ios")
            self.assertEqual(code, 3, out)
            first = (next(self.repo.state.glob("acme__notes/feature-x")) / "latest").read_text().strip()
            code, out = self.cli(fake, "run", "--platforms", "android")  # same second, same commit
            self.assertEqual(code, 3, out)
            code, out = self.cli(fake, "wait", "--run", first, "--timeout", "5000")
            self.assertEqual(code, 0, out)
            base = next(self.repo.state.glob("acme__notes/feature-x"))
            self.assertNotEqual((base / "latest").read_text().strip(), first, "a waiter must not move latest")
            code, out = self.cli(fake, "wait", "--timeout", "5000")
            self.assertEqual(code, 1, out)
            ledger = json.loads((base / "ledger.json").read_text())
            self.assertEqual({p: e["verdict"] for p, e in ledger["platforms"].items()},
                             {"ios": "pass", "android": "fail"})

    def test_dirty_tree_is_refused(self):
        with FakeDevin() as fake:
            (self.repo.path / "README.md").write_text("dirty\n")
            code, _ = self.cli(fake, "run")
            self.assertEqual(code, 4)


class ReleaseE2E(unittest.TestCase):
    def test_release_runs_argv_command_only_on_a_green_head(self):
        repo = helpers.ProductRepo(platforms='["ios"]')
        clock = helpers.FakeClock()
        marker = repo.state.parent / "released.txt"
        qa = repo.path / ".devin" / "qa.toml"
        script = f"open({str(marker)!r}, 'w').write('ok')"
        repo.commit_file(".devin/qa.toml", qa.read_text() +
                         f'\n[release]\ncommand = ["python3", "-c", "{script}"]\nauto = true\n')
        try:
            with FakeDevin({"ios": "pass"}) as fake:
                env = {**helpers.clean_env(), **repo.env(fake.base)}
                with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", clock.time), \
                        mock.patch("time.sleep", clock.sleep), contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(["-C", str(repo.path), "release"]), 2)
                    self.assertFalse(marker.exists())
                    self.assertEqual(cli.main(["-C", str(repo.path), "run"]), 3)
                    self.assertEqual(cli.main(["-C", str(repo.path), "wait", "--timeout", "5000"]), 0)
                    self.assertEqual(cli.main(["-C", str(repo.path), "release"]), 0)
            self.assertEqual(marker.read_text(), "ok")
        finally:
            repo.cleanup()


class BundleE2E(unittest.TestCase):
    def test_bundle_mode_uploads_and_attaches(self):
        repo = helpers.ProductRepo(mode="bundle", platforms='["ios"]')
        clock = helpers.FakeClock()
        try:
            with FakeDevin({"ios": "pass"}) as fake:
                env = {**helpers.clean_env(), **repo.env(fake.base)}
                with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", clock.time), \
                        mock.patch("time.sleep", clock.sleep), contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(["-C", str(repo.path), "run"]), 3)
                    self.assertEqual(cli.main(["-C", str(repo.path), "wait", "--timeout", "5000"]), 0)
                self.assertEqual(len(fake.uploads), 1)
                body = fake.created_bodies[0]
                self.assertIn("attachment_urls", body)
                self.assertNotIn("repos", body)
                self.assertIn(fake.uploads[0], body["prompt"])
                remote_refs = helpers.git(repo.remote, "for-each-ref", "--format=%(refname)")
                self.assertNotIn("client-validation-devin", remote_refs)
        finally:
            repo.cleanup()


class DryRun(unittest.TestCase):
    def test_dry_run_renders_prompts_without_api(self):
        repo = helpers.ProductRepo()
        try:
            env = {**helpers.clean_env(), "CLIENT_VALIDATION_DEVIN_HOME": str(repo.state)}
            out = io.StringIO()
            with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(["-C", str(repo.path), "run", "--dry-run"]), 0)
            prompts = list(repo.state.rglob("prompt.md"))
            self.assertEqual(len(prompts), 3)
            android_prompt = (prompts[0].parent.parent / "android" / "prompt.md").read_text()
            self.assertIn("Platform `android` on Devin VM `linux`", android_prompt)
            self.assertNotIn("client-validation-devin", helpers.git(repo.remote, "for-each-ref", "--format=%(refname)"))
        finally:
            repo.cleanup()


if __name__ == "__main__":
    unittest.main()
