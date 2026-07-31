import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import db
import discovery


class DiscoveryTests(unittest.TestCase):
    def test_first_run_has_official_lanes_and_skips_intern(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["JOB_COPILOT_DATA_DIR"] = tmp
            conn = db.connect(tmp)
            stamp = db.now_iso()
            conn.execute("INSERT INTO profiles(id,name_masked,created_at,updated_at) VALUES(?,?,?,?)", ("p", "X同学", stamp, stamp))
            conn.execute("INSERT INTO campaigns(id,profile_id,name,route,active,preferences_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", ("c", "p", "校招", "campus", 1, "{}", stamp, stamp))
            conn.commit(); conn.close()
            from io import StringIO
            import contextlib
            out = StringIO()
            with contextlib.redirect_stdout(out):
                discovery.main(["plan", "--campaign", "c", "--data-dir", tmp])
            payload = json.loads(out.getvalue())
            lane_ids = {lane["lane_id"] for lane in payload["lanes"]}
            self.assertIn("campus-official-launch", lane_ids)
            self.assertNotIn("campus-intern", lane_ids)
            os.environ.pop("JOB_COPILOT_DATA_DIR", None)

    def test_social_campaign_uses_social_lanes(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = db.connect(tmp)
            stamp = db.now_iso()
            conn.execute("INSERT INTO profiles(id,name_masked,created_at,updated_at) VALUES(?,?,?,?)", ("p", "X同学", stamp, stamp))
            conn.execute("INSERT INTO campaigns(id,profile_id,name,route,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", ("c", "p", "社招", "social", 1, stamp, stamp))
            conn.commit(); conn.close()
            from io import StringIO
            import contextlib
            out = StringIO()
            with contextlib.redirect_stdout(out):
                discovery.main(["plan", "--campaign", "c", "--data-dir", tmp])
            payload = json.loads(out.getvalue())
            lane_ids = {lane["lane_id"] for lane in payload["lanes"]}
            self.assertIn("social-official-watchlist", lane_ids)
            self.assertIn("social-aggregator-boss", lane_ids)


if __name__ == "__main__":
    unittest.main()
