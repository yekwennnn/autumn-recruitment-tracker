import unittest
from pathlib import Path
import sys
import contextlib
import io
import os
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from db import redact
import jobctl


class PrivacyTests(unittest.TestCase):
    def test_sensitive_values_are_redacted(self):
        text = redact("password=secret cookie=abc 身份证号=110101199001010011 电话 13812345678 a@example.com")
        for value in ("secret", "abc", "110101199001010011", "13812345678", "a@example.com"):
            self.assertNotIn(value, text)

    def test_profile_show_masks_contacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["JOB_COPILOT_DATA_DIR"] = tmp
            jobctl.main(["profile", "update", "--profile-json", '{"phone":"13812345678","email":"a@example.com"}'])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                jobctl.main(["profile", "show", "--json"])
            self.assertNotIn("13812345678", output.getvalue())
            self.assertNotIn("a@example.com", output.getvalue())
            os.environ.pop("JOB_COPILOT_DATA_DIR", None)

    def test_profile_update_rejects_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["JOB_COPILOT_DATA_DIR"] = tmp
            with self.assertRaises(SystemExit) as caught:
                jobctl.main(["profile", "update", "--profile-json", '{"password":"secret"}'])
            self.assertEqual(caught.exception.code, 2)
            conn = __import__("db").connect(tmp)
            self.assertEqual(conn.execute("SELECT application_profile_json FROM profiles").fetchone(), None)
            conn.close()
            os.environ.pop("JOB_COPILOT_DATA_DIR", None)


if __name__ == "__main__":
    unittest.main()
