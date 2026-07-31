import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db
import jobctl


class InterviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["JOB_COPILOT_DATA_DIR"] = self.tmp.name
        jobctl.main([
            "campaign", "create", "--id", "social-campaign", "--name", "社招",
            "--route", "social", "--activate",
        ])
        conn = db.connect(self.tmp.name)
        stamp = "2026-07-31T09:00:00+08:00"
        conn.execute(
            """INSERT INTO resume_versions(
                 id,profile_id,kind,label,active_base,created_at
               ) VALUES(?,?,?,?,?,?)""",
            ("base", "profile-default", "base", "基础", 1, stamp),
        )
        conn.execute(
            """INSERT INTO postings(
                 id,campaign_id,canonical_key,company,title,route,status,
                 first_seen_at,jd_text
               ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                "post", "social-campaign", "post", "示例公司", "数据产品经理",
                "social", "active", stamp, "负责企业数据产品和 BI 平台建设",
            ),
        )
        conn.execute(
            """INSERT INTO applications(
                 id,posting_id,resume_version_id,channel,applied_at,
                 current_stage,last_update_at
               ) VALUES(?,?,?,?,?,?,?)""",
            ("app", "post", "base", "官网", stamp, "一面", stamp),
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        os.environ.pop("JOB_COPILOT_DATA_DIR", None)
        self.tmp.cleanup()

    def test_social_session_progress_completion_and_summary_only_storage(self):
        jobctl.main([
            "interview", "start", "--id", "session", "--application-id", "app",
            "--round-label", "一面", "--focus", "产品",
        ])
        conn = db.connect(self.tmp.name)
        row = conn.execute(
            "SELECT * FROM interview_sessions WHERE id='session'"
        ).fetchone()
        plan = json.loads(row["plan_json"])
        conn.close()
        self.assertEqual(row["question_count"], 6)
        self.assertEqual(row["status"], "started")
        self.assertEqual(plan["route"], "social")
        self.assertEqual(plan["specificity"], "jd_grounded")
        self.assertEqual(plan["categories"][1]["category"], "achievement_scope")

        secret_verbatim = "这是不应该进入数据库的逐字原回答：我先做了非常具体的事情。"
        jobctl.main([
            "interview", "progress", "--id", "session", "--question-index", "1",
            "--relevance", "20", "--evidence", "19", "--structure", "16",
            "--role-fit", "17", "--clarity", "8",
            "--issue-tags", "结论偏后,结果需补证据",
            "--improvement-summary", "先说结论，再使用一个已确认项目说明行动和结果",
        ])
        jobctl.main([
            "interview", "complete", "--id", "session",
            "--strengths-json", '["项目描述具体"]',
            "--gaps-json", '["结论出现较晚"]',
            "--actions-json", '["重练90秒自我介绍"]',
            "--followups-json", '["职责边界是什么？"]',
            "--reverse-questions-json", '["三个月成功标准是什么？"]',
            "--review-points-json", '["先结论后证据"]',
        ])
        conn = db.connect(self.tmp.name)
        stored = conn.execute(
            """SELECT plan_json,progress_json,summary_json,status,overall_score
               FROM interview_sessions WHERE id='session'"""
        ).fetchone()
        events = conn.execute(
            """SELECT event_type FROM application_events
               WHERE application_id='app'"""
        ).fetchall()
        conn.close()
        serialized = "\n".join(str(item) for item in stored)
        self.assertNotIn(secret_verbatim, serialized)
        self.assertEqual(stored["status"], "completed")
        self.assertEqual(stored["overall_score"], 80)
        self.assertIn("mock_interview_completed", {row[0] for row in events})

        shown = io.StringIO()
        with contextlib.redirect_stdout(shown):
            jobctl.main(["interview", "show", "--id", "session"])
        self.assertIn('"overall_score": 80', shown.getvalue())
        self.assertNotIn(secret_verbatim, shown.getvalue())
        export_path = Path(self.tmp.name) / "export.json"
        with contextlib.redirect_stdout(io.StringIO()):
            jobctl.main(["export", "--output", str(export_path)])
        exported = export_path.read_text(encoding="utf-8")
        self.assertIn('"interview_sessions"', exported)
        self.assertNotIn(secret_verbatim, exported)

    def test_standalone_campus_session_marks_missing_jd(self):
        jobctl.main([
            "interview", "start", "--id", "campus-session",
            "--profile-id", "profile-default", "--company", "校园公司",
            "--title", "产品培训生", "--route", "campus",
        ])
        conn = db.connect(self.tmp.name)
        row = conn.execute(
            "SELECT plan_json FROM interview_sessions WHERE id='campus-session'"
        ).fetchone()
        conn.close()
        plan = json.loads(row[0])
        self.assertEqual(plan["specificity"], "limited_without_jd")
        self.assertEqual(plan["categories"][1]["category"], "project_internship")

    def test_abandon_and_score_validation(self):
        jobctl.main([
            "interview", "start", "--id", "abandoned", "--application-id", "app",
        ])
        jobctl.main([
            "interview", "abandon", "--id", "abandoned", "--reason", "用户提前结束",
        ])
        conn = db.connect(self.tmp.name)
        self.assertEqual(
            conn.execute(
                "SELECT status FROM interview_sessions WHERE id='abandoned'"
            ).fetchone()[0],
            "abandoned",
        )
        conn.close()

        jobctl.main([
            "interview", "start", "--id", "bad-score", "--application-id", "app",
        ])
        with self.assertRaises(SystemExit) as caught:
            jobctl.main([
                "interview", "progress", "--id", "bad-score",
                "--question-index", "1", "--relevance", "26",
                "--evidence", "20", "--structure", "15", "--role-fit", "15",
                "--clarity", "8", "--improvement-summary", "需要更聚焦",
            ])
        self.assertEqual(caught.exception.code, 2)

    def test_transcript_shaped_plan_is_rejected(self):
        with self.assertRaises(SystemExit) as caught:
            jobctl.main([
                "interview", "start", "--id", "unsafe", "--application-id", "app",
                "--plan-json", '{"answer":"逐字回答"}',
            ])
        self.assertEqual(caught.exception.code, 2)
        conn = db.connect(self.tmp.name)
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM interview_sessions WHERE id='unsafe'"
            ).fetchone()[0],
            0,
        )
        conn.close()

    def test_skill_documents_interview_trigger_and_honesty(self):
        root = Path(__file__).resolve().parents[1]
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        reference = (root / "references" / "interview.md").read_text(encoding="utf-8")
        self.assertIn("收到面试邀请", skill)
        self.assertIn("询问是否模拟", skill)
        self.assertIn("不得虚构项目", reference)
        self.assertIn("一次只问一题", reference)


if __name__ == "__main__":
    unittest.main()
