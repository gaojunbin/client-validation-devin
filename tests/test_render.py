"""report.md must give the coding agent everything it needs to act: every issue in full, test failures, evidence."""

import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401
from client_validation_devin.collect import evidence_index, heavy_kind
from client_validation_devin.render import render_markdown


def summary() -> dict:
    minor = {"id": "macos-004", "severity": "minor", "category": "logic", "title": "Fallback shortcut shown as Fn",
             "scenario": "setup-guide", "actual": "Badge says 检测到 Fn", "expected": "Names the fallback chord",
             "suspected_location": "src/renderer/onboarding/ShortcutStep.tsx:32",
             "suggested_fix": "Propagate the shortcut source", "confidence": "high",
             "evidence_paths": ["/tmp/x/r1-macos__setup-guide__1000x750_light_zh_std__05.png"]}
    platform = {
        "verdict": "fail", "reasons": ["automated tests failed"], "session_url": "https://app.devin.ai/sessions/1",
        "usage": 0, "summary": "Cold-run tests failed once.", "phases": {"tests": {"status": "fail"}},
        "tests": {"passed": 174, "failed": 0, "failures": [{"name": "installer > mounts", "message": "ENOENT"}]},
        "gating": [], "warnings": [minor], "fixed_issue_ids": [], "spec_feedback": ["Home has no side rail."],
        "scenarios": [{"id": "setup-guide", "status": "fail"}],
        "not_downloaded": [{"name": "r1-macos__launch__complete-evidence_light_zh_std__01.zip", "kind": "archive",
                            "url": "https://app.devin.ai/attachments/u/a.zip"}],
        "missing_evidence": [], "errors": [], "evidence_counts": {"layout-ai": 37, "launch": 22},
        "evidence_index": "/tmp/x/macos/evidence.md", "folder": "/tmp/x/macos",
    }
    return {"run_id": "r", "round": 1, "product": "Acme Notes", "repo": "a/b", "branch": "main", "commit": "a" * 40,
            "exit_code": 1, "overall": "fail", "platforms": {"macos": platform}, "needs_human": [],
            "shared_root_causes": [], "next": "Fix what failed (macos: automated tests failed)."}


class RenderTest(unittest.TestCase):
    def test_issues_below_the_gate_keep_their_fix_guidance(self):
        text = render_markdown(summary())
        self.assertIn("### Issues below the gate", text)
        self.assertIn("Suggested fix (high confidence): Propagate the shortcut source", text)
        self.assertIn("Suspected location: src/renderer/onboarding/ShortcutStep.tsx:32", text)
        self.assertIn("Evidence: /tmp/x/r1-macos__setup-guide__1000x750_light_zh_std__05.png", text)

    def test_test_failures_evidence_and_downloads_are_listed(self):
        text = render_markdown(summary())
        self.assertIn("Tests: passed 174, failed 0", text)
        self.assertIn("- installer > mounts: ENOENT", text)
        self.assertIn("Evidence (59 files, index /tmp/x/macos/evidence.md): layout-ai 37, launch 22", text)
        self.assertIn("archive: r1-macos__launch__complete-evidence_light_zh_std__01.zip", text)
        self.assertNotIn("Usage", text)  # self-serve plans report no usage through the API

    def test_reports_written_before_the_rename_still_render(self):
        data = summary()
        platform = data["platforms"]["macos"]
        platform["videos"] = [{"name": "r1.mp4", "url": "https://x/r1.mp4"}]
        for key in ("not_downloaded", "evidence_counts", "evidence_index", "tests"):
            platform.pop(key)
        self.assertIn("video: r1.mp4", render_markdown(data))


class EvidenceTest(unittest.TestCase):
    def test_index_groups_files_by_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            counts = evidence_index(folder, {
                "r1-ios__layout-home__iphone-se_dark_en_xl__02.png": "/a/2.png",
                "r1-ios__layout-home__iphone-17_light_en_std__01.png": "/a/1.png",
                "r1-ios__launch__iphone-17_light_en_std__01.png": "/a/l.png",
                "odd-name.png": "/a/o.png",
            })
            self.assertEqual(counts, {"launch": 1, "layout-home": 2, "other": 1})
            text = (folder / "evidence.md").read_text()
            self.assertIn("## layout-home (2)", text)

    def test_heavy_files_are_not_downloaded(self):
        self.assertEqual(heavy_kind({"name": "a.zip"}), "archive")
        self.assertEqual(heavy_kind({"name": "a.bin", "content_type": "video/mp4"}), "video")
        self.assertEqual(heavy_kind({"name": "a.png", "content_type": "image/png"}), "")


if __name__ == "__main__":
    unittest.main()
