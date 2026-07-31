import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import autofill


class AutofillTests(unittest.TestCase):
    def test_fill_never_submits_and_blocks_sensitive_required_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "profile.json"
            profile_path.write_text(json.dumps({"application_profile": {"name": "叶同学", "email": "a@example.com"}}), encoding="utf-8")
            calls = []
            original = {
                "new_target": autofill.new_target,
                "inspect_controls": autofill.inspect_controls,
                "fill_control": autofill.fill_control,
                "invalid_controls": autofill.invalid_controls,
                "set_files": autofill.set_files,
                "jobctl": autofill.jobctl,
            }
            autofill.new_target = lambda url: "target-1"
            controls = [
                {"index": 0, "type": "text", "name": "name", "id": "", "placeholder": "", "aria": "", "label": "姓名", "required": True, "value": "", "haystack": "name 姓名"},
                {"index": 1, "type": "email", "name": "email", "id": "", "placeholder": "", "aria": "", "label": "邮箱", "required": True, "value": "", "haystack": "email 邮箱"},
                {"index": 2, "type": "text", "name": "id_number", "id": "", "placeholder": "", "aria": "", "label": "身份证号", "required": True, "value": "", "haystack": "id_number 身份证号"},
            ]
            autofill.inspect_controls = lambda target: controls
            autofill.fill_control = lambda target, control, value: calls.append((control["name"], value)) or True
            autofill.invalid_controls = lambda target: [controls[2]]
            autofill.set_files = lambda *args: calls.append(("set_files", args))
            def fake_jobctl(args, extra):
                if extra[0:2] == ["form", "start"]:
                    return {"form_session_id": "form-1"}
                calls.append(("jobctl", extra))
                return {"ok": True}
            autofill.jobctl = fake_jobctl
            try:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    autofill.fill(SimpleNamespace(
                        profile_json=str(profile_path), posting_id="post", resume_version_id="base",
                        url="https://example.com/apply", resume_file=None, photo_file=None, data_dir=tmp,
                    ))
                output = out.getvalue()
                self.assertIn('"submitted": false', output)
                self.assertIn('"status": "blocked"', output)
                self.assertTrue(any(item[0] == "name" for item in calls if isinstance(item, tuple)))
                self.assertFalse(any(item[0] == "submit" for item in calls if isinstance(item, tuple)))
            finally:
                for key, value in original.items():
                    setattr(autofill, key, value)


if __name__ == "__main__":
    unittest.main()
