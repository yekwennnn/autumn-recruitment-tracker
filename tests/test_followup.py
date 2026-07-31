import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db
import digest
import jobctl


class ApplicationFollowupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["JOB_COPILOT_DATA_DIR"] = self.tmp.name
        jobctl.main([
            "campaign", "create", "--id", "campaign", "--name", "社招",
            "--route", "social", "--digest-time", "09:00", "--activate",
        ])
        conn = db.connect(self.tmp.name)
        stamp = "2026-07-31T08:00:00+08:00"
        conn.execute(
            """INSERT INTO resume_versions(
                 id,profile_id,kind,label,active_base,created_at
               ) VALUES(?,?,?,?,?,?)""",
            ("base", "profile-default", "base", "基础", 1, stamp),
        )
        for posting_id, title in (("post-1", "岗位一"), ("post-2", "岗位二")):
            conn.execute(
                """INSERT INTO postings(
                     id,campaign_id,canonical_key,company,title,route,status,
                     first_seen_at,application_url
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    posting_id, "campaign", posting_id, "示例公司", title,
                    "social", "active", stamp, f"https://example.test/{posting_id}",
                ),
            )
        conn.commit()
        conn.close()

    def tearDown(self):
        os.environ.pop("JOB_COPILOT_DATA_DIR", None)
        self.tmp.cleanup()

    def _submit(self, app_id="app-1", posting_id="post-1", **extra):
        argv = [
            "application", "mark-submitted", "--id", app_id,
            "--posting-id", posting_id, "--resume-version-id", "base",
            "--applied-at", "2026-07-31T16:00:00+08:00",
        ]
        for key, value in extra.items():
            argv.extend([f"--{key.replace('_', '-')}", value])
        jobctl.main(argv)

    def test_submission_schedules_third_calendar_day_and_event(self):
        self._submit()
        conn = db.connect(self.tmp.name)
        app = conn.execute(
            "SELECT * FROM applications WHERE id='app-1'"
        ).fetchone()
        events = conn.execute(
            "SELECT event_type FROM application_events WHERE application_id='app-1'"
        ).fetchall()
        conn.close()
        self.assertEqual(app["next_action_at"], "2026-08-03T09:00:00+08:00")
        self.assertEqual(
            {row[0] for row in events},
            {"submitted", "followup_scheduled"},
        )

    def test_explicit_next_action_overrides_default(self):
        self._submit(next_action_at="2026-08-10T14:30:00+08:00")
        conn = db.connect(self.tmp.name)
        value = conn.execute(
            "SELECT next_action_at FROM applications WHERE id='app-1'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(value, "2026-08-10T14:30:00+08:00")

    def test_digest_due_then_no_update_reschedules_three_days(self):
        self._submit()
        before = io.StringIO()
        with mock.patch.object(digest, "now_iso", return_value="2026-08-02T10:00:00+08:00"):
            with contextlib.redirect_stdout(before):
                jobctl.main(["digest", "render", "--campaign", "campaign"])
        before_section = before.getvalue().split("## 二、投递待跟进", 1)[1].split(
            "## 三、今日高匹配岗位", 1
        )[0]
        self.assertNotIn("状态检查时间", before_section)

        due = io.StringIO()
        with mock.patch.object(digest, "now_iso", return_value="2026-08-03T09:00:00+08:00"):
            with contextlib.redirect_stdout(due):
                jobctl.main(["digest", "render", "--campaign", "campaign"])
        due_section = due.getvalue().split("## 二、投递待跟进", 1)[1].split(
            "## 三、今日高匹配岗位", 1
        )[0]
        self.assertIn("示例公司 · 岗位一", due_section)
        self.assertIn("application check-status --id app-1 --result no-update", due_section)

        ignored = io.StringIO()
        with mock.patch.object(digest, "now_iso", return_value="2026-08-04T09:00:00+08:00"):
            with contextlib.redirect_stdout(ignored):
                jobctl.main(["digest", "render", "--campaign", "campaign"])
        ignored_section = ignored.getvalue().split(
            "## 二、投递待跟进", 1
        )[1].split("## 三、今日高匹配岗位", 1)[0]
        self.assertIn("示例公司 · 岗位一", ignored_section)

        jobctl.main([
            "application", "check-status", "--id", "app-1",
            "--result", "no-update", "--date", "2026-08-03T10:00:00+08:00",
        ])
        conn = db.connect(self.tmp.name)
        app = conn.execute(
            "SELECT next_action_at FROM applications WHERE id='app-1'"
        ).fetchone()
        event = conn.execute(
            """SELECT event_type FROM application_events
               WHERE application_id='app-1'
               ORDER BY occurred_at DESC LIMIT 1"""
        ).fetchone()
        conn.close()
        self.assertEqual(app[0], "2026-08-06T09:00:00+08:00")
        self.assertEqual(event[0], "status_checked_no_update")

    def test_stop_and_terminal_stage_clear_reminder_without_deleting(self):
        self._submit()
        jobctl.main([
            "application", "check-status", "--id", "app-1", "--result", "stop",
        ])
        conn = db.connect(self.tmp.name)
        self.assertIsNone(
            conn.execute(
                "SELECT next_action_at FROM applications WHERE id='app-1'"
            ).fetchone()[0]
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0], 1
        )
        conn.close()

        jobctl.main([
            "application", "check-status", "--id", "app-1",
            "--result", "updated", "--stage", "拒绝",
        ])
        conn = db.connect(self.tmp.name)
        app = conn.execute(
            "SELECT closed,next_action_at,current_stage FROM applications WHERE id='app-1'"
        ).fetchone()
        conn.close()
        self.assertEqual((app[0], app[1], app[2]), (1, None, "拒绝"))
        conn = db.connect(self.tmp.name)
        event_types = {
            row[0] for row in conn.execute(
                "SELECT event_type FROM application_events WHERE application_id='app-1'"
            ).fetchall()
        }
        conn.close()
        self.assertIn("submitted", event_types)
        self.assertIn("followup_stopped", event_types)
        self.assertIn("stage_update", event_types)

    def test_ambiguous_company_does_not_update_first_application(self):
        self._submit()
        self._submit(app_id="app-2", posting_id="post-2")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            jobctl.main([
                "application", "check-status", "--id", "示例公司",
                "--result", "stop",
            ])
        self.assertIn('"ambiguous": true', output.getvalue())
        conn = db.connect(self.tmp.name)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM applications WHERE next_action_at IS NOT NULL"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(remaining, 2)

    def test_form_draft_does_not_create_application_reminder(self):
        jobctl.main([
            "form", "start", "--id", "form", "--posting-id", "post-1",
            "--resume-version-id", "base", "--form-url", "https://example.test/apply",
        ])
        jobctl.main(["form", "ready", "form"])
        conn = db.connect(self.tmp.name)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0], 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
