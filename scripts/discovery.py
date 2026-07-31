#!/usr/bin/env python3
"""Plan and account for source lanes.

Actual web research is performed by the active agent with web-access.  This
script only decides which lanes are due and records the run, so it remains
deterministic and safe in environments without browser access.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from db import connect, now_iso, json_dumps, rows_dict, transaction
except ImportError:
    from .db import connect, now_iso, json_dumps, rows_dict, transaction


CAMPUS_LANES = [
    ("campus-official-launch", "daily", "official"),
    ("campus-official-watchlist", "daily", "official"),
    ("campus-wechat-launch", "daily", "wechat"),
    ("campus-wechat-watchlist", "daily", "wechat"),
    ("campus-aggregator-newcompany", "weekly", "aggregator"),
    ("campus-nowcoder", "weekly", "aggregator"),
    ("campus-intern", "weekly", "aggregator-intern"),
]
SOCIAL_LANES = [
    ("social-official-watchlist", "daily", "official"),
    ("social-official-newcompany", "weekly", "official"),
    ("social-wechat-watchlist", "daily", "wechat"),
    ("social-aggregator-liepin", "weekly", "aggregator"),
    ("social-aggregator-boss", "weekly", "aggregator-login"),
    ("social-aggregator-other", "weekly", "aggregator"),
]
APP_TIMEZONE = ZoneInfo("Asia/Shanghai")


def _due(last_run, frequency, full):
    if full or not last_run:
        return True
    try:
        last = datetime.fromisoformat(last_run)
    except ValueError:
        return True
    age = datetime.now(APP_TIMEZONE) - last.astimezone(APP_TIMEZONE)
    return age >= timedelta(days=1 if frequency == "daily" else 7)


def plan(args):
    conn = connect(args.data_dir)
    campaign = conn.execute("SELECT * FROM campaigns WHERE id=?", (args.campaign,)).fetchone()
    if campaign is None:
        raise SystemExit(f"找不到 campaign：{args.campaign}")
    lanes = CAMPUS_LANES if campaign["route"] == "campus" else SOCIAL_LANES
    prefs = json.loads(campaign["preferences_json"] or "{}")
    include_intern = bool(prefs.get("include_internships", False))
    previous = conn.execute("SELECT MAX(completed_at) FROM discovery_runs WHERE campaign_id=?", (args.campaign,)).fetchone()[0]
    full = previous is None
    if previous:
        try:
            full = datetime.now(APP_TIMEZONE) - datetime.fromisoformat(previous).astimezone(APP_TIMEZONE) >= timedelta(days=7)
        except ValueError:
            full = True
    selected = []
    for lane_id, frequency, channel in lanes:
        if lane_id.endswith("intern") and not include_intern:
            continue
        yield_row = conn.execute("SELECT * FROM source_yield WHERE campaign_id=? AND lane_id=?", (args.campaign, lane_id)).fetchone()
        if _due(yield_row["last_run_at"] if yield_row else None, frequency, full):
            selected.append({"lane_id": lane_id, "frequency": frequency, "channel": channel, "scope_hint": min(int(campaign["daily_quota"]) * 4, 40)})
    payload = {
        "campaign_id": args.campaign,
        "route": campaign["route"],
        "full_sweep": full,
        "daily_quota": campaign["daily_quota"],
        "lanes": selected,
        "known_companies": json.loads(campaign["priority_companies_json"] or "[]"),
    }
    conn.close()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def commit(args):
    conn = connect(args.data_dir)
    plan_path = args.plan
    payload = json.loads(open(plan_path, encoding="utf-8").read())
    stamp = now_iso()
    results = json.loads(open(args.results, encoding="utf-8").read()) if args.results else {}
    with transaction(conn):
        run_id = f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        conn.execute("INSERT INTO discovery_runs(id,campaign_id,mode,lanes_json,started_at,completed_at,result_count,error_json) VALUES(?,?,?,?,?,?,?,?)", (run_id, payload["campaign_id"], "full" if payload.get("full_sweep") else "lean", json_dumps(payload.get("lanes", [])), stamp, stamp, int(results.get("result_count", 0)), json_dumps(results.get("errors", []))))
        for lane in payload.get("lanes", []):
            lane_id = lane["lane_id"]
            result = results.get("lanes", {}).get(lane_id, {})
            new_count = int(result.get("new_count", 0))
            qualified = int(result.get("qualified_count", 0))
            row = conn.execute("SELECT * FROM source_yield WHERE campaign_id=? AND lane_id=?", (payload["campaign_id"], lane_id)).fetchone()
            zero_streak = 0 if new_count else (int(row["zero_streak"]) + 1 if row else 1)
            conn.execute("""INSERT INTO source_yield(campaign_id,lane_id,runs,new_count,qualified_count,zero_streak,last_run_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(campaign_id,lane_id) DO UPDATE SET
                runs=runs+1,new_count=new_count+excluded.new_count,qualified_count=qualified_count+excluded.qualified_count,
                zero_streak=excluded.zero_streak,last_run_at=excluded.last_run_at""", (payload["campaign_id"], lane_id, 1, new_count, qualified, zero_streak, stamp))
    conn.close()
    print(json.dumps({"run_id": run_id, "committed": True}, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan"); p.add_argument("--campaign", required=True); p.add_argument("--data-dir"); p.set_defaults(func=plan)
    p = sub.add_parser("commit"); p.add_argument("--plan", required=True); p.add_argument("--results"); p.add_argument("--data-dir"); p.set_defaults(func=commit)
    args = ap.parse_args(argv); args.func(args)


if __name__ == "__main__":
    main()
