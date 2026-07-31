import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db
import jobctl


class CliFlowTests(unittest.TestCase):
    def test_posting_dedupe_match_recommendation_and_draft(self):
        fixture_dir = Path(__file__).parent / "fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["JOB_COPILOT_DATA_DIR"] = tmp
            jobctl.main(["init"])
            jobctl.main(["campaign", "create", "--name", "校招", "--route", "campus", "--activate"])
            conn = db.connect(tmp)
            campaign_id = conn.execute("SELECT id FROM campaigns WHERE active=1").fetchone()[0]
            conn.close()
            jobctl.main(["resume", "import", "--file", str(fixture_dir / "campus-resume.txt"), "--id", "base", "--set-base"])
            jobctl.main(["posting", "import-json", "--campaign", campaign_id, "--input", str(fixture_dir / "postings.json")])
            conn = db.connect(tmp)
            posting = conn.execute("SELECT * FROM postings WHERE company='示例科技'").fetchone()
            conn.close()
            evaluation = [{
                "posting_id": posting["id"], "resume_version_id": "base", "eligible": True,
                "score": 84, "coverage": 90, "confidence": "high", "hard_failures": [],
                "dimensions": {"hard_skills": 27, "experience": 21, "education": 18, "certificates": 8, "preferences": 10},
                "evidence": ["简历有 Python 和 SQL"], "gaps": [], "actions": [], "jd_hash": posting["jd_hash"],
            }]
            eval_path = Path(tmp) / "evaluation.json"
            eval_path.write_text(json.dumps(evaluation, ensure_ascii=False), encoding="utf-8")
            jobctl.main(["match", "record", "--input", str(eval_path)])
            conn = db.connect(tmp)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0], 1)
            rec = conn.execute("SELECT * FROM recommendations").fetchone()
            conn.close()
            jobctl.main(["form", "start", "--posting-id", posting["id"], "--resume-version-id", "base", "--form-url", "https://example.com/apply"])
            conn = db.connect(tmp)
            self.assertEqual(conn.execute("SELECT status FROM recommendations WHERE id=?", (rec["id"],)).fetchone()[0], "preparing")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0], 0)
            conn.close()
            os.environ.pop("JOB_COPILOT_DATA_DIR", None)

    def test_official_and_aggregator_same_role_merge_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["JOB_COPILOT_DATA_DIR"] = tmp
            jobctl.main(["campaign", "create", "--name", "校招", "--route", "campus", "--activate"])
            conn = db.connect(tmp)
            campaign_id = conn.execute("SELECT id FROM campaigns WHERE active=1").fetchone()[0]
            conn.close()
            payload = [
                {"company": "合并公司", "title": "数据分析师", "city": "上海", "route": "campus", "employment_type": "全职", "source_platform": "公司官网", "source_url": "https://merge.test/job/7", "official_url": "https://merge.test/job/7", "application_url": "https://merge.test/apply/7", "source_tier": "A", "jd_text": "Python SQL", "official_job_id": "7"},
                {"company": "合并公司", "title": "数据分析师", "city": "上海", "route": "campus", "employment_type": "全职", "source_platform": "聚合平台", "source_url": "https://aggregator.test/merge/7", "official_url": None, "application_url": "https://aggregator.test/merge/7", "source_tier": "C", "jd_text": "Python SQL"},
            ]
            source = Path(tmp) / "postings.json"
            source.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            jobctl.main(["posting", "import-json", "--campaign", campaign_id, "--input", str(source)])
            conn = db.connect(tmp)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM posting_sources").fetchone()[0], 2)
            conn.close()
            os.environ.pop("JOB_COPILOT_DATA_DIR", None)


if __name__ == "__main__":
    unittest.main()
