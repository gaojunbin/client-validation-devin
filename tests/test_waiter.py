import unittest

import helpers  # noqa: F401
from client_validation_devin.sessions import new_platform_state
from client_validation_devin.waiter import ACTION_COOLDOWN, MAX_AUTO_REPLIES, NUDGE_GRACE, SETTLE_SECONDS, decide

NOW = 10_000.0


def state(**overrides):
    s = new_platform_state("macos", "r1-aaaaaa")
    s.update(state="running", session_id="devin-1", started_at=NOW - 1000, deadline=NOW + 1000,
             last_action_at=NOW - ACTION_COOLDOWN - 1)
    s.update(overrides)
    return s


def session(status="running", detail="working", report=None):
    return {"status": status, "status_detail": detail, "structured_output": report}


FINAL = {"round_token": "r1-aaaaaa", "report_status": "final"}


class DecideTest(unittest.TestCase):
    def test_final_report_for_this_round_is_done(self):
        self.assertEqual(decide(state(), session(detail="finished", report=FINAL), NOW)[0], "done")

    def test_final_report_while_still_working_settles_first(self):
        working = session(detail="working", report=FINAL)
        self.assertEqual(decide(state(), working, NOW)[0], "settle")
        self.assertEqual(decide(state(final_seen_at=NOW - 60), working, NOW)[0], "settle")
        self.assertEqual(decide(state(final_seen_at=NOW - SETTLE_SECONDS - 1), working, NOW)[0], "done")
        self.assertEqual(decide(state(final_seen_at=NOW - 60), session(detail="finished", report=FINAL), NOW)[0],
                         "done")

    def test_report_from_previous_round_is_ignored(self):
        old = {"round_token": "r0-bbbbbb", "report_status": "final"}
        self.assertEqual(decide(state(), session(report=old), NOW)[0], "wait")

    def test_in_progress_report_is_not_done(self):
        self.assertEqual(decide(state(), session(report={**FINAL, "report_status": "in_progress"}), NOW)[0], "wait")

    def test_waiting_for_user_gets_auto_replies_then_blocks(self):
        s = session(detail="waiting_for_user")
        self.assertEqual(decide(state(), s, NOW)[0], "auto_reply")
        self.assertEqual(decide(state(auto_replies=MAX_AUTO_REPLIES), s, NOW)[0], "blocked")

    def test_cooldown_after_an_action(self):
        self.assertEqual(decide(state(last_action_at=NOW - 10), session(detail="waiting_for_user"), NOW)[0], "wait")

    def test_finished_without_report_is_nudged_once(self):
        s = session(detail="finished")
        self.assertEqual(decide(state(), s, NOW)[0], "nudge")
        nudged = state(nudged_at=NOW - 10)
        self.assertEqual(decide(nudged, s, NOW)[0], "wait")
        late = state(nudged_at=NOW - NUDGE_GRACE - 1)
        self.assertEqual(decide(late, s, NOW)[0], "blocked")

    def test_sleeping_session_is_nudged(self):
        self.assertEqual(decide(state(), session(status="suspended", detail="inactivity"), NOW)[0], "nudge")

    def test_quota_is_infra(self):
        self.assertEqual(decide(state(), session(status="suspended", detail="out_of_quota"), NOW)[0], "infra")

    def test_exit_without_report_blocks(self):
        self.assertEqual(decide(state(), session(status="exit", detail=None), NOW)[0], "blocked")

    def test_time_budget(self):
        self.assertEqual(decide(state(deadline=NOW - 1), session(), NOW)[0], "finalize")
        graced = state(deadline=NOW - 1, grace_deadline=NOW - 1)
        self.assertEqual(decide(graced, session(), NOW)[0], "terminate")
        self.assertEqual(decide(state(deadline=NOW - 1, grace_deadline=NOW + 60), session(), NOW)[0], "wait")


if __name__ == "__main__":
    unittest.main()
