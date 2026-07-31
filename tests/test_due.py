import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db
import jobctl


class DueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["JOB_COPILOT_DATA_DIR"] = self.tmp.name
        jobctl.main(["init"])
        jobctl.main(["campaign", "create", "--name", "测试", "--route", "campus", "--activate"])
        conn = db.connect(self.tmp.name)
        stamp = db.now_iso()
        conn.execute("INSERT INTO resume_versions(id,profile_id,kind,label,active_base,created_at) VALUES(?,?,?,?,?,?)", ("base", "profile-default", "base", "基础", 1, stamp))
        conn.execute("INSERT INTO postings(id,campaign_id,canonical_key,company,title,route,status,first_seen_at) VALUES(?,?,?,?,?,?,?,?)", ("post", conn.execute("SELECT id FROM campaigns").fetchone()[0], "x", "公司", "岗位", "campus", "active", stamp))
        conn.execute("INSERT INTO posting_sources(id,posting_id,tier,platform,url,discovered_at,verified_at) VALUES(?,?,?,?,?,?,?)", ("src", "post", "A", "官网", "https://x.test", stamp, stamp))
        conn.execute("INSERT INTO matches(id,posting_id,resume_version_id,eligible,score,coverage,confidence,jd_hash,evaluated_at) VALUES(?,?,?,?,?,?,?,?,?)", ("match", "post", "base", 1, 80, 80, "high", "h", stamp))
        conn.execute("INSERT INTO recommendations(id,campaign_id,posting_id,match_id,resume_version_id,status,recommended_at,decision_due_at) VALUES(?,?,?,?,?,?,?,?)", ("rec", conn.execute("SELECT id FROM campaigns").fetchone()[0], "post", "match", "base", "pending", "2020-01-01T09:00:00+08:00", "2020-01-02T09:00:00+08:00"))
        conn.commit(); conn.close()

    def tearDown(self):
        os.environ.pop("JOB_COPILOT_DATA_DIR", None)
        self.tmp.cleanup()

    def test_due_list_and_archive(self):
        from io import StringIO
        import contextlib
        out = StringIO()
        with contextlib.redirect_stdout(out):
            jobctl.main(["due", "list"])
        self.assertIn('"id": "rec"', out.getvalue())
        jobctl.main(["due", "archive", "rec"])
        conn = db.connect(self.tmp.name)
        self.assertEqual(conn.execute("SELECT status FROM recommendations WHERE id='rec'").fetchone()[0], "archived")
        conn.close()

    def test_form_progress_resets_clock_and_application_removes_due(self):
        jobctl.main(["form", "start", "--id", "form", "--posting-id", "post", "--resume-version-id", "base", "--form-url", "https://x.test/apply"])
        conn = db.connect(self.tmp.name)
        due = conn.execute("SELECT decision_due_at,last_progress_at,status FROM recommendations WHERE id='rec'").fetchone()
        self.assertEqual(due[2], "preparing")
        self.assertGreater(due[0], db.now_iso())
        stamp = db.now_iso()
        conn.execute("INSERT INTO applications(id,posting_id,resume_version_id,channel,applied_at,current_stage,last_update_at) VALUES(?,?,?,?,?,?,?)", ("app", "post", "base", "官网", stamp, "已投递", stamp))
        conn.commit(); conn.close()
        from io import StringIO
        import contextlib
        output = StringIO()
        with contextlib.redirect_stdout(output):
            jobctl.main(["due", "list"])
        self.assertNotIn('"id": "rec"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
