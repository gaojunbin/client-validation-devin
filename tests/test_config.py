import tomllib
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets the import path)
from client_validation_devin.config import parse_config
from client_validation_devin.credentials import parse_env_file
from client_validation_devin.errors import ConfigError

EXAMPLE = helpers.REPO / "skills" / "client-validation-devin" / "assets" / "qa.example.toml"


def load(text: str):
    return parse_config(tomllib.loads(text), path=Path("qa.toml"), root=Path("."))


class ConfigTest(unittest.TestCase):
    def test_example_parses(self):
        config = load(EXAMPLE.read_text())
        self.assertEqual(config.run.default_platforms, ("ios", "android", "macos", "linux"))
        self.assertEqual(config.platforms["android"].vm, "linux")
        self.assertIn("major", config.run.fail_on)
        self.assertEqual([s.id for s in config.scenarios], ["first-launch", "create-note", "settings-theme"])

    def test_unknown_key_is_rejected(self):
        with self.assertRaisesRegex(ConfigError, "unknown key"):
            load(EXAMPLE.read_text().replace("max_rounds = 5", "max_round = 5"))

    def test_platform_needs_build(self):
        text = '[product]\nname="a"\nsummary="b"\n[platforms.ios]\nvm="macos"\n'
        with self.assertRaisesRegex(ConfigError, "build is required"):
            load(text)

    def test_default_platform_needs_table(self):
        text = ('[product]\nname="a"\nsummary="b"\n[run]\ndefault_platforms=["ios","android"]\n'
                '[platforms.ios]\nbuild="x"\n')
        with self.assertRaisesRegex(ConfigError, "without"):
            load(text)

    def test_duplicate_scenarios(self):
        scenario = '[[scenarios]]\nid="a"\nsteps="s"\nexpect="e"\n'
        text = '[product]\nname="a"\nsummary="b"\n[platforms.ios]\nbuild="x"\n' + scenario * 2
        with self.assertRaisesRegex(ConfigError, "duplicate"):
            load(text)

    def test_vm_defaults_per_platform(self):
        config = load('[product]\nname="a"\nsummary="b"\n[platforms.ios]\nbuild="x"\n[platforms.android]\nbuild="y"\n')
        self.assertEqual(config.platforms["ios"].vm, "macos")
        self.assertEqual(config.platforms["android"].vm, "linux")

    def test_env_file(self):
        values = parse_env_file('# c\nexport DEVIN_API_KEY="cog_x"\nDEVIN_ORG_ID=org-1\nbad line\n')
        self.assertEqual(values, {"DEVIN_API_KEY": "cog_x", "DEVIN_ORG_ID": "org-1"})


if __name__ == "__main__":
    unittest.main()
