import json
import tomllib
import unittest
from pathlib import Path

import helpers  # noqa: F401
from client_validation_devin.config import PLATFORMS, parse_config
from client_validation_devin.prompt import ASSETS, JobContext, render_prompt, report_schema, select_scenarios

EXAMPLE = helpers.REPO / "skills" / "client-validation-devin" / "assets" / "qa.example.toml"


def example_config():
    data = tomllib.loads(EXAMPLE.read_text())
    data["platforms"]["web"] = {"vm": "linux", "build": "npm run build"}
    return parse_config(data, path=Path("qa.toml"), root=Path("."))


def job(platform: str, **extra) -> JobContext:
    return JobContext(run_id="20261115-000000-abc1234", round=2, round_token="r2-abc123", platform=platform,
                      vm="macos", repo="acme/notes", commit="a" * 40, delivery_text="pushed",
                      checkout_steps="1. checkout", budget_minutes=90, **extra)


class PromptTest(unittest.TestCase):
    def test_every_platform_renders_without_placeholders(self):
        config = example_config()
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                text = render_prompt(config, job(platform, changed_files=[]), list(config.scenarios))
                self.assertNotIn("{{", text)
                self.assertIn("round token `r2-abc123`", text)
                self.assertIn("## Platform guide", text)
                self.assertIn("r2-", text)
                self.assertIn("create-note", text)

    def test_platform_layout_overrides_global_layout(self):
        data = tomllib.loads(EXAMPLE.read_text())
        data["platforms"]["macos"]["themes"] = ["light"]
        data["platforms"]["macos"]["text_scale"] = ["default"]
        config = parse_config(data, path=Path("qa.toml"), root=Path("."))
        macos = render_prompt(config, job("macos", changed_files=[]), [])
        ios = render_prompt(config, job("ios", changed_files=[]), [])
        self.assertIn("- themes: light; locales: en, de; text scale: default", macos)
        self.assertIn("- themes: light, dark; locales: en, de; text scale: default, largest", ios)

    def test_change_under_test_comes_first(self):
        config = example_config()
        focus = "Added a 字号 slider; expect no clipping."
        text = render_prompt(config, job("ios", focus=focus, changed_files=[]), [])
        self.assertLess(text.index("## Change under test"), text.index("## Rules"))
        self.assertIn("Added a 字号 slider; expect no clipping.", text)
        self.assertIn("verify it first as a scenario with id `change`", text)
        bare = render_prompt(config, job("ios", changed_files=[]), [])
        self.assertIn("skip the `change` scenario", bare)

    def test_previous_issues_are_listed(self):
        config = example_config()
        issue = {"id": "ios-001", "severity": "major", "category": "layout", "title": "Overlap", "screen": "Editor"}
        text = render_prompt(config, job("ios", previous_issues=[issue], changed_files=None), [])
        self.assertIn("ios-001 [major/layout] Overlap (Editor)", text)
        self.assertIn("unknown (no base branch found)", text)

    def test_p1_scenarios_follow_changed_paths(self):
        config = example_config()
        ids = lambda changed: [s.id for s in select_scenarios(config, "ios", changed)]  # noqa: E731
        self.assertEqual(ids(["lib/editor/x.dart"]), ["first-launch", "create-note"])
        self.assertEqual(ids(["lib/settings/page.dart"]), ["first-launch", "create-note", "settings-theme"])
        self.assertEqual(ids(None), ["first-launch", "create-note", "settings-theme"])
        self.assertEqual([s.id for s in select_scenarios(config, "ios", [], ["create-note"])], ["create-note"])

    def test_schema_is_valid_json_under_64kb(self):
        raw = (ASSETS / "report.schema.json").read_text()
        self.assertLess(len(raw.encode()), 64 * 1024)
        schema = report_schema()
        self.assertEqual(schema["$schema"], "http://json-schema.org/draft-07/schema#")
        self.assertNotIn("http", json.dumps(schema).replace("http://json-schema.org/draft-07/schema#", ""))


if __name__ == "__main__":
    unittest.main()
