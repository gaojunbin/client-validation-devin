import unittest

import helpers  # noqa: F401
from client_validation_devin.verdict import exit_code, judge, shared_root_causes, stuck, update_streaks

GATE = frozenset({"blocker", "critical", "major"})
PASS_PHASES = {n: {"status": "pass"} for n in ("checkout", "build", "tests", "launch", "scenarios", "layout")}


def report(**overrides):
    base = {"verdict": "pass", "phases": dict(PASS_PHASES), "issues": [], "scenarios": [{"id": "a", "status": "pass"}]}
    base.update(overrides)
    return base


def issue(i, severity="major", title="Save button overlaps title", category="layout", scenario="create-note"):
    return {"id": i, "severity": severity, "category": category, "title": title, "scenario": scenario,
            "actual": "x", "evidence": ["f.png"]}


class JudgeTest(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(judge("ios", "done", "", report(), GATE).verdict, "pass")

    def test_minor_issue_is_a_warning(self):
        v = judge("ios", "done", "", report(issues=[issue("ios-1", "minor")]), GATE)
        self.assertEqual((v.verdict, len(v.warnings)), ("pass", 1))

    def test_major_issue_fails(self):
        self.assertEqual(judge("ios", "done", "", report(issues=[issue("ios-1")]), GATE).verdict, "fail")

    def test_build_failure_fails(self):
        phases = {**PASS_PHASES, "build": {"status": "fail"}}
        self.assertEqual(judge("ios", "done", "", report(phases=phases), GATE).verdict, "fail")

    def test_environment_blocked(self):
        phases = {**PASS_PHASES, "build": {"status": "blocked"}}
        self.assertEqual(judge("ios", "done", "", report(phases=phases), GATE).verdict, "blocked")

    def test_missing_report_and_infra_block(self):
        self.assertEqual(judge("ios", "blocked", "no report", None, GATE).verdict, "blocked")
        self.assertIn("infrastructure", judge("ios", "infra", "quota", None, GATE).reasons[0])

    def test_failed_scenario_without_issue_fails(self):
        r = report(scenarios=[{"id": "a", "status": "fail"}])
        v = judge("ios", "done", "", r, GATE)
        self.assertEqual(v.verdict, "fail")
        self.assertIn("scenario a failed and no issue explains it (read its notes)", v.reasons)

    def test_scenario_notes_citing_an_issue_explain_the_failure(self):
        r = report(scenarios=[{"id": "language-switch", "status": "fail", "notes": "Clips at XL (android-001)."}],
                   issues=[issue("android-001", scenario="layout matrix")])
        self.assertNotIn("no issue explains", " ".join(judge("android", "done", "", r, GATE).reasons))

    def test_fail_verdict_without_issues_fails(self):
        self.assertEqual(judge("ios", "done", "", report(verdict="fail"), GATE).verdict, "fail")


class StreakTest(unittest.TestCase):
    def test_issue_is_stuck_after_two_fix_rounds(self):
        streaks = []
        for _ in range(3):
            streaks = update_streaks(streaks, "ios", [issue("ios-001")])
        self.assertEqual(streaks[0]["count"], 3)
        self.assertEqual(len(stuck(streaks, GATE)), 1)

    def test_renamed_issue_matches_by_fingerprint(self):
        first = update_streaks([], "ios", [issue("ios-001")])
        second = update_streaks(first, "ios", [issue("ios-007")])
        self.assertEqual(second[0]["count"], 2)

    def test_fixed_issue_resets(self):
        first = update_streaks([], "ios", [issue("ios-001")])
        self.assertEqual(update_streaks(first, "ios", []), [])


class AggregateTest(unittest.TestCase):
    def test_shared_root_cause_groups_platforms(self):
        a = judge("ios", "done", "", report(issues=[issue("ios-1")]), GATE)
        b = judge("android", "done", "", report(issues=[issue("android-4")]), GATE)
        groups = shared_root_causes({"ios": a.gating + a.warnings, "android": b.gating + b.warnings})
        self.assertEqual(len(groups), 1)

    def test_exit_codes(self):
        p = judge("ios", "done", "", report(), GATE)
        f = judge("ios", "done", "", report(issues=[issue("i")]), GATE)
        b = judge("ios", "blocked", "x", None, GATE)
        self.assertEqual(exit_code({"a": p}, False), 0)
        self.assertEqual(exit_code({"a": p, "b": f, "c": b}, False), 1)
        self.assertEqual(exit_code({"a": p, "c": b}, False), 2)
        self.assertEqual(exit_code({"a": p}, True), 5)


if __name__ == "__main__":
    unittest.main()
