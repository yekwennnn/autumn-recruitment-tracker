#!/usr/bin/env python3
"""Manage state/match_insights.json — the accumulator that makes matching and
resume tailoring smarter over time. Sole writer of that file.

Subcommands:
  show         Print a compact markdown block, ready to paste into deep-eval
               or tailoring prompts.
  ingest-eval  Accumulate jd_keywords frequencies from an evaluated.json.
  add-fact     Record a user-confirmed real fact (honesty-pass answers).
  log-version  Record a tailored resume version's outcome.
  note         Append a free-form lesson note.
"""
import argparse
import json
from datetime import date, datetime

EMPTY_INSIGHTS = {
    "schema_version": 1,
    "updated_at": None,
    "jd_demand_stats": {},
    "confirmed_facts": [],
    "version_performance": [],
    "notes": [],
}


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_insights(path):
    return load_json(path, json.loads(json.dumps(EMPTY_INSIGHTS)))


def save_insights(path, data):
    data["updated_at"] = datetime.now().astimezone().isoformat()
    save_json(path, data)


def cmd_show(args):
    data = load_insights(args.insights)
    stats = data.get("jd_demand_stats", {})
    facts = data.get("confirmed_facts", [])
    perf = data.get("version_performance", [])
    notes = data.get("notes", [])
    if not (stats or facts or perf or notes):
        print("（暂无累积洞察）")
        return
    lines = ["## 累积求职洞察"]
    if stats:
        lines.append("### 该方向JD高频要求（TOP15）")
        top = sorted(stats.items(), key=lambda kv: -kv[1].get("count", 0))[:15]
        for word, info in top:
            lines.append(f"- {word}（{info.get('count', 0)}次，最近 {info.get('last_seen', '')}）")
    if facts:
        lines.append("### 已核实的真实素材（改简历不要重复追问）")
        for f in facts:
            lines.append(f"- {f.get('claim', '')}｜{f.get('detail', '')}｜阶段：{f.get('stage', '')}｜确认于 {f.get('confirmed_at', '')}")
    if perf:
        lines.append("### 简历版本战绩")
        for p in perf:
            tags = "、".join(p.get("tags", []))
            lines.append(f"- {p.get('version', '')} → {p.get('target', '')}：{p.get('score_after', '')}分（tags：{tags}）")
    if notes:
        lines.append("### 经验笔记")
        for n in notes:
            lines.append(f"- {n.get('text', '')}（{n.get('date', '')}）")
    print("\n".join(lines))


def cmd_ingest_eval(args):
    data = load_insights(args.insights)
    evaluated = load_json(args.input, [])
    today = date.today().isoformat()
    stats = data.setdefault("jd_demand_stats", {})
    for item in evaluated:
        if not item.get("fetched"):
            continue
        for word in item.get("jd_keywords", []):
            word = word.strip()
            if not word:
                continue
            entry = stats.setdefault(word, {"count": 0, "last_seen": today})
            entry["count"] += 1
            entry["last_seen"] = today
    save_insights(args.insights, data)
    print(f"jd_demand_stats 现有 {len(stats)} 个词")


def cmd_add_fact(args):
    data = load_insights(args.insights)
    today = date.today().isoformat()
    facts = data.setdefault("confirmed_facts", [])
    for f in facts:
        if f.get("claim") == args.claim:
            f["detail"] = args.detail
            f["stage"] = args.stage
            f["confirmed_at"] = today
            break
    else:
        facts.append({"claim": args.claim, "detail": args.detail,
                      "stage": args.stage, "confirmed_at": today})
    save_insights(args.insights, data)
    print(f"confirmed_facts 现有 {len(facts)} 条")


def cmd_log_version(args):
    data = load_insights(args.insights)
    data.setdefault("version_performance", []).append({
        "version": args.version,
        "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
        "score_after": args.score,
        "target": args.target,
        "date": date.today().isoformat(),
    })
    save_insights(args.insights, data)
    print(f"version_performance 现有 {len(data['version_performance'])} 条")


def cmd_note(args):
    data = load_insights(args.insights)
    data.setdefault("notes", []).append({"text": args.text, "date": date.today().isoformat()})
    save_insights(args.insights, data)
    print(f"notes 现有 {len(data['notes'])} 条")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("show")
    p.add_argument("--insights", required=True)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("ingest-eval")
    p.add_argument("--insights", required=True)
    p.add_argument("--input", required=True)
    p.set_defaults(func=cmd_ingest_eval)

    p = sub.add_parser("add-fact")
    p.add_argument("--insights", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--detail", required=True)
    p.add_argument("--stage", required=True)
    p.set_defaults(func=cmd_add_fact)

    p = sub.add_parser("log-version")
    p.add_argument("--insights", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--tags")
    p.add_argument("--score", type=int, required=True)
    p.add_argument("--target", required=True)
    p.set_defaults(func=cmd_log_version)

    p = sub.add_parser("note")
    p.add_argument("--insights", required=True)
    p.add_argument("--text", required=True)
    p.set_defaults(func=cmd_note)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
