"""`client-validation-devin env apply` against the fake API: create, update, keep git-backed blueprints."""

import contextlib
import io
import os
import unittest
from unittest import mock

import helpers
from client_validation_devin import cli
from fake_devin import FakeDevin


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


if __name__ == "__main__":
    unittest.main()
