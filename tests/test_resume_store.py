import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from extract_resume import extract_file
import jobctl
import db


class ResumeStoreTests(unittest.TestCase):
    def test_import_text_resume_creates_archive_and_hash(self):
        fixture = Path(__file__).parent / "fixtures" / "campus-resume.txt"
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["JOB_COPILOT_DATA_DIR"] = tmp
            jobctl.main(["resume", "import", "--file", str(fixture), "--id", "base", "--set-base"])
            conn = db.connect(tmp)
            row = conn.execute("SELECT * FROM resume_versions WHERE id='base'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["active_base"], 1)
            self.assertTrue(Path(tmp, row["text_path"]).exists())
            conn.close()
            os.environ.pop("JOB_COPILOT_DATA_DIR", None)

    def test_extract_text(self):
        fixture = Path(__file__).parent / "fixtures" / "social-resume.txt"
        text = extract_file(fixture)
        self.assertIn("产品经理", text)


if __name__ == "__main__":
    unittest.main()
