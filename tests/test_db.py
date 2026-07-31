import os
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db


class DatabaseTests(unittest.TestCase):
    def test_schema_and_pragmas(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(tmp)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("campaigns", tables)
            self.assertIn("applications", tables)
            self.assertIn("interview_sessions", tables)
            conn.close()
            self.assertTrue(Path(tmp, "resumes", "versions").is_dir())

    def test_canonical_key_and_redaction(self):
        self.assertEqual(db.canonical_key("示例", "数据岗", "上海", "https://x.test/a?utm_source=x"), "示例|数据岗|上海|https://x.test/a")
        self.assertEqual(db.canonical_key("示例", "数据岗", "上海", official_job_id="JOB-7"), "示例|job-7")
        redacted = db.redact("电话=13812345678 email=test@example.com 身份证号=110101199001010011")
        self.assertNotIn("13812345678", redacted)
        self.assertNotIn("110101199001010011", redacted)
        self.assertNotIn("test@example.com", redacted)

    def test_legacy_database_is_backed_up_before_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "job-copilot.sqlite3"
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE legacy(value TEXT)")
            conn.execute("INSERT INTO legacy VALUES('keep')")
            conn.execute("PRAGMA user_version=1")
            conn.commit(); conn.close()
            migrated = db.connect(tmp)
            self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], 2)
            self.assertIsNotNone(
                migrated.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='interview_sessions'"
                ).fetchone()
            )
            migrated.close()
            backups = list((Path(tmp) / "backups").glob("job-copilot-*.sqlite3"))
            self.assertEqual(len(backups), 1)
            backup_conn = sqlite3.connect(backups[0])
            self.assertEqual(backup_conn.execute("SELECT value FROM legacy").fetchone()[0], "keep")
            backup_conn.close()

    def test_transaction_rolls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(tmp)
            with self.assertRaises(RuntimeError):
                with db.transaction(conn):
                    conn.execute("INSERT INTO profiles(id,name_masked,created_at,updated_at) VALUES(?,?,?,?)", ("p", "X", db.now_iso(), db.now_iso()))
                    raise RuntimeError("rollback")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM profiles").fetchone()[0], 0)
            conn.close()

    def test_config_adds_v2_defaults_without_overwriting_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.mkdir(parents=True, exist_ok=True)
            (root / "config.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "timezone": "Asia/Shanghai",
                        "daily_digest_time": "08:30",
                    }
                ),
                encoding="utf-8",
            )
            config = db.load_config(root)
            self.assertEqual(config["schema_version"], 2)
            self.assertEqual(config["daily_digest_time"], "08:30")
            self.assertEqual(config["application_followup_days_default"], 3)
            persisted = json.loads((root / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(persisted["schema_version"], 2)


if __name__ == "__main__":
    unittest.main()
