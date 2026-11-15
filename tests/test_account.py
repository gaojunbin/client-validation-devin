"""`login` writes the key safely; `available` decides whether a machine validates on Devin."""

import contextlib
import io
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers
from client_validation_devin import cli
from client_validation_devin.account import save_env_values
from fake_devin import FakeDevin


class SaveEnvTest(unittest.TestCase):
    def test_new_file_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg" / "env"
            save_env_values(path, {"DEVIN_API_KEY": "cog_a", "DEVIN_ORG_ID": ""})
            self.assertEqual(path.read_text(), "DEVIN_API_KEY=cog_a\n")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_updates_in_place_and_keeps_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "env"
            path.write_text("# mine\nexport DEVIN_API_KEY=cog_old\nOTHER=1\n")
            save_env_values(path, {"DEVIN_API_KEY": "cog_new", "DEVIN_ORG_ID": "org-1"})
            self.assertEqual(path.read_text(), "# mine\nDEVIN_API_KEY=cog_new\nOTHER=1\nDEVIN_ORG_ID=org-1\n")

    def test_symlinked_file_is_written_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "icloud-env"
            real.write_text("DEVIN_API_KEY=cog_old\n")
            link = Path(tmp) / "env"
            link.symlink_to(real)
            save_env_values(link, {"DEVIN_API_KEY": "cog_new"})
            self.assertTrue(link.is_symlink())
            self.assertEqual(real.read_text(), "DEVIN_API_KEY=cog_new\n")


class LoginAndAvailableTest(unittest.TestCase):
    def setUp(self):
        self.repo = helpers.ProductRepo()
        self.env_file = Path(self.repo.tmp.name) / "config" / "env"

    def tearDown(self):
        self.repo.cleanup()

    def call(self, fake, *args, stdin="", with_key=True):
        env = {**helpers.clean_env(), "DEVIN_API_BASE": fake.base,
               "CLIENT_VALIDATION_DEVIN_ENV_FILE": str(self.env_file),
               "CLIENT_VALIDATION_DEVIN_HOME": str(self.repo.state)}
        if with_key:
            env["DEVIN_API_KEY"] = "cog_testkey123456"
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("sys.stdin", io.StringIO(stdin)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = cli.main(["-C", str(self.repo.path), *args])
        return code, out.getvalue()

    def test_login_checks_the_key_and_stores_the_detected_org(self):
        with FakeDevin() as fake:
            code, out = self.call(fake, "login", "--key-stdin", stdin="cog_testkey123456\n", with_key=False)
            self.assertEqual(code, 0, out)
            self.assertIn("organization org-test", out)
            self.assertEqual(self.env_file.read_text(), "DEVIN_API_KEY=cog_testkey123456\nDEVIN_ORG_ID=org-test\n")

    def test_login_rejects_bad_keys(self):
        with FakeDevin() as fake:
            code, out = self.call(fake, "login", "--key-stdin", stdin="apk_legacy\n", with_key=False)
            self.assertEqual(code, 4)
            self.assertFalse(self.env_file.exists())
            code, out = self.call(fake, "login", "--key-stdin", stdin="cog_wrong\n", with_key=False)
            self.assertNotEqual(code, 0)
            self.assertFalse(self.env_file.exists())

    def test_available_needs_config_and_credentials(self):
        with FakeDevin() as fake:
            self.assertEqual(self.call(fake, "available", "--online")[0], 0)
            code, out = self.call(fake, "available", with_key=False)
            self.assertEqual(code, 2)
            self.assertIn("no Devin credentials", out)
            (self.repo.path / ".devin" / "qa.toml").unlink()
            code, out = self.call(fake, "available")
            self.assertEqual(code, 2)
            self.assertIn("project not onboarded", out)


if __name__ == "__main__":
    unittest.main()
