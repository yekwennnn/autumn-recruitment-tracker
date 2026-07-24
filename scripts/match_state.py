#!/usr/bin/env python3
"""Deep-eval state machine. Sole script writer of the `match` field in
state/seen_postings.json (dedupe.py never touches `match`).

Subcommands:
  pending  Select postings awaiting deep eval (never re-selects scored /
           jd_unavailable ones), compute deterministic quick scores from the
           profile keywords, cap by config resume.max_deep_evals_per_run.
  record   Merge orchestrator evaluation results back into state; failed
           fetches accumulate attempts until jd_unavailable.
"""
import argparse
import json
import sys
from datetime import date

EMPTY_MATCH = {"status": "pending", "quick_score": 0, "jd_fetch_attempts": 0}


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


def quick_score(rec, match_keywords):
    title = (rec.get("title") or "").lower()
    highlight = (rec.get("highlight") or "").lower()
    s = 0
    for kw in match_keywords:
        k = kw.strip().lower()
        if not k:
            continue
        if k in title:
            s += 2
        elif k in highlight:
            s += 1
    return s


def cmd_pending(args):
    state = load_json(args.state, {"postings": {}})
    config = load_json(args.config, {})
    profile = load_json(args.profile, {})
    match_keywords = profile.get("match_keywords", []) or []

    limit = args.limit
    if limit is None:
        limit = config.get("resume", {}).get("max_deep_evals_per_run", 15)

    candidates = []
    for h, rec in state.get("postings", {}).items():
        m = rec.get("match")
        if m is not None and m.get("status") in ("scored", "jd_unavailable"):
            continue
        m = rec.setdefault("match", dict(EMPTY_MATCH))
        m["quick_score"] = quick_score(rec, match_keywords)
        candidates.append(rec)

    candidates.sort(key=lambda r: r.get("first_seen", ""), reverse=True)
    candidates.sort(key=lambda r: -r["match"]["quick_score"])
    selected = candidates[:limit]

    save_json(args.state, state)

    out = [{
        "id": r.get("id", ""), "company": r.get("company", ""), "title": r.get("title", ""),
        "city": r.get("city", ""), "source_url": r.get("source_url", ""),
        "quick_score": r["match"]["quick_score"],
        "jd_fetch_attempts": r["match"].get("jd_fetch_attempts", 0),
    } for r in selected]
    save_json(args.output, out)
    print(f"本次入选深评 {len(selected)} 条 / 剩余待深评 {len(candidates) - len(selected)} 条")


def cmd_record(args):
    state = load_json(args.state, {"postings": {}})
    config = load_json(args.config, {})
    evaluated = load_json(args.input, [])
    postings = state.get("postings", {})
    max_attempts = config.get("resume", {}).get("jd_fetch_max_attempts", 2)
    today = date.today().isoformat()

    scored = retry = exhausted = skipped = 0
    for item in evaluated:
        rec = postings.get(item.get("id"))
        if rec is None:
            sys.stderr.write(f"warning: id 不在 state 中，跳过：{item.get('id')}\n")
            continue
        m = rec.setdefault("match", dict(EMPTY_MATCH))
        if item.get("fetched"):
            if m.get("status") == "scored" and not args.force:
                skipped += 1
                continue
            m.update({
                "status": "scored",
                "jd_url": item.get("jd_url", ""),
                "jd_summary": item.get("jd_summary", ""),
                "jd_keywords": item.get("jd_keywords", []),
                "score": int(item["score"]),
                "pros": item.get("pros", ""),
                "gaps": item.get("gaps", ""),
                "evaluated_at": today,
                "resume_version": item.get("resume_version", ""),
            })
            scored += 1
        else:
            m["jd_fetch_attempts"] = int(m.get("jd_fetch_attempts", 0)) + 1
            m["last_fetch_error"] = item.get("reason", "")
            if m["jd_fetch_attempts"] >= max_attempts:
                m["status"] = "jd_unavailable"
                exhausted += 1
            else:
                m["status"] = "pending"
                retry += 1

    save_json(args.state, state)
    print(json.dumps({"scored": scored, "retry": retry, "exhausted": exhausted, "skipped": skipped},
                     ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("pending")
    p.add_argument("--state", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--limit", type=int)
    p.set_defaults(func=cmd_pending)

    p = sub.add_parser("record")
    p.add_argument("--state", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_record)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
