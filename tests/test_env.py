"""`client-validation-devin env apply` against the fake API: create, update, keep git-backed blueprints."""

import contextlib
import io
import os
import unittest
from unittest import mock

import helpers
from client_validation_devin import cli
from client_validation_devin.envcmd import environment_gap, wait_build
from fake_devin import FakeDevin


class Builds:
    """A client whose build list changes on every call (the last snapshot repeats)."""

    org_id = "org-new"

    def __init__(self, *snapshots):
        self.snapshots = list(snapshots)

    def list_blueprints(self):
        return [{"blueprint_id": "bp1", "repo_name": "acme/notes", "created_at": 1000}]

    def list_builds(self):
        return self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]


def build(build_id, status, created_at):
    return {"build_id": build_id, "status": status, "created_at": created_at}


class EnvApply(unittest.TestCase):
    def setUp(self):
        self.repo = helpers.ProductRepo(platforms='["ios"]')
        self.blueprint = self.repo.path / ".devin" / "blueprint.yaml"
        self.blueprint.write_text("runs-on: macos\nmaintenance: |\n  echo v1\n")

    def tearDown(self):
        self.repo.cleanup()

    def env(self, fake: FakeDevin, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        env = {**helpers.clean_env(), **self.repo.env(fake.base)}
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(out):
            code = cli.main(["-C", str(self.repo.path), "env", *args])
        return code, out.getvalue()

    def test_create_then_update(self):
        with FakeDevin() as fake:
            code, out = self.env(fake, "apply", "--wait")
            self.assertEqual(code, 0, out)
            self.assertEqual(len(fake.blueprints), 1)
            self.assertEqual(fake.blueprints[0]["repo_name"], "acme/notes")
            self.assertIn("succeeded", out)
            self.assertIn("BUILD SUCCESSFUL", out)  # build-log summary follows a waited build
            self.assertIn("WARN: iOS warm build failed", out)
            self.assertIn("1 warning(s)", out)
            self.assertNotIn("command: npm ci", out)

            self.blueprint.write_text("runs-on: macos\nmaintenance: |\n  echo v2\n")
            code, out = self.env(fake, "apply")
            self.assertEqual(code, 0, out)
            self.assertEqual(len(fake.blueprints), 1, "existing blueprint must be updated, not duplicated")
            self.assertEqual(fake.blueprint_patches, 1)
            self.assertIn("echo v2", fake.blueprints[0]["contents"])

    def test_git_backed_blueprint_is_not_overwritten(self):
        with FakeDevin() as fake:
            fake.blueprints.append({"blueprint_id": "bp9", "repo_name": "acme/notes", "source": "git"})
            code, out = self.env(fake, "apply")
            self.assertEqual(code, 4, out)
            self.assertIn("git-backed", out)
            self.assertEqual(fake.blueprint_patches, 0)
            code, out = self.env(fake, "apply", "--switch-from-git")
            self.assertEqual(code, 0, out)
            self.assertEqual(fake.blueprint_patches, 1)


class EnvironmentGate(unittest.TestCase):
    """A round does not start sessions in an organization that has not built this repository's environment."""

    def setUp(self):
        self.repo = helpers.ProductRepo(platforms='["ios"]')
        self.repo.commit_file(".devin/blueprint.yaml", "runs-on: macos\nmaintenance: |\n  echo v1\n")

    def tearDown(self):
        self.repo.cleanup()

    def cli(self, fake: FakeDevin, *args: str) -> tuple[int, str]:
        out = io.StringIO()
        env = {**helpers.clean_env(), **self.repo.env(fake.base)}
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(out):
            code = cli.main(["-C", str(self.repo.path), *args])
        return code, out.getvalue()

    def test_round_waits_for_this_organizations_environment(self):
        with FakeDevin({"ios": "pass"}) as fake:
            code, out = self.cli(fake, "run")
            self.assertEqual(code, 2, out)
            self.assertIn("has no environment for acme/notes", out)
            self.assertIn("env apply --wait", out)
            fake.build_status = "running"
            self.assertEqual(self.cli(fake, "env", "apply")[0], 0)
            code, out = self.cli(fake, "run")
            self.assertEqual(code, 2, out)
            self.assertIn("still building", out)
            fake.builds["b1"]["status"] = "failed"
            code, out = self.cli(fake, "run")
            self.assertEqual(code, 2, out)
            self.assertIn("no successful environment build", out)
            self.assertEqual(fake.created_bodies, [])
            fake.builds["b1"]["status"] = "succeeded"
            code, out = self.cli(fake, "run")
            self.assertEqual(code, 3, out)
            self.assertEqual(len(fake.created_bodies), 1)

    def test_bundle_delivery_waits_only_for_an_existing_blueprint(self):
        self.repo.cleanup()
        self.repo = helpers.ProductRepo(mode="bundle", platforms='["ios"]')
        self.repo.commit_file(".devin/blueprint.yaml", "runs-on: macos\n")
        with FakeDevin({"ios": "pass"}) as fake:
            fake.blueprints.append({"blueprint_id": "bp1", "repo_name": "acme/notes", "created_at": 1})
            fake.builds["b0"] = {"build_id": "b0", "status": "running", "created_at": 2}
            code, out = self.cli(fake, "run")
            self.assertEqual(code, 2, out)
            self.assertIn("still building", out)
            fake.blueprints.clear()
            code, out = self.cli(fake, "run")
            self.assertEqual(code, 3, out)

    def test_secrets_missing_in_this_organization_are_named(self):
        qa = self.repo.path / ".devin" / "qa.toml"
        self.repo.commit_file(".devin/qa.toml", qa.read_text() +
                              '\n[secrets]\ndevin_secret_names = ["TEST_LOGIN", "TEST_PASSWORD"]\n')
        with FakeDevin({"ios": "pass"}) as fake:
            self.assertEqual(self.cli(fake, "env", "apply", "--wait")[0], 0)
            fake.secrets.append({"key": "TEST_LOGIN", "access_type": "org", "secret_id": "s1"})
            code, out = self.cli(fake, "doctor")
            self.assertIn("warn  secrets: Devin organization org-test has no organization or personal secret "
                          "TEST_PASSWORD (", out)
            code, out = self.cli(fake, "run")
            self.assertEqual(code, 3, out)
            self.assertIn("note: Devin organization org-test has no organization or personal secret TEST_PASSWORD",
                          out)
            fake.secrets.append({"key": "TEST_PASSWORD", "access_type": "personal", "secret_id": "s2"})
            self.repo.commit_file("lib/editor/editor.dart", "v2")
            code, out = self.cli(fake, "run")
            self.assertEqual(code, 3, out)
            self.assertNotIn("secret", out.split("Run ")[0])

    def gap(self, *builds):
        return environment_gap(Builds(list(builds)), self.repo.path, "acme/notes")

    def test_a_trigger_is_ready_only_when_all_its_platform_builds_are_done(self):
        linux, macos = build("b-linux", "succeeded", 2000), build("b-macos", "running", 2000)
        self.assertIn("still building", self.gap(linux, macos))
        self.assertEqual(self.gap(linux, {**macos, "status": "failed"}), "")
        older = [build("a-linux", "succeeded", 1100), build("a-macos", "succeeded", 1101)]
        self.assertEqual(self.gap(*older, macos), "", "a rebuild in progress does not block a built environment")
        self.assertIn("no successful environment build", self.gap(build("z", "succeeded", 900)))

    def test_wait_build_waits_for_every_build_of_the_trigger(self):
        first = [build("b-linux", "succeeded", 2000), build("b-macos", "running", 2000)]
        done = [build("b-linux", "succeeded", 2000), build("b-macos", "succeeded", 2000)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(wait_build(Builds(first, done), "b-linux", 600, poll_seconds=0), 0)
        self.assertIn("build b-macos: running", out.getvalue())
        self.assertIn("build b-macos: succeeded", out.getvalue())
        failed = [build("b-linux", "succeeded", 2000), build("b-macos", "failed", 2000)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(wait_build(Builds(failed), "b-linux", 600, poll_seconds=0), 2)


if __name__ == "__main__":
    unittest.main()
