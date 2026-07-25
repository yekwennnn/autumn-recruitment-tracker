#!/usr/bin/env python3
"""Track what actually got applied to, with which resume version, and how far
it went. Sole writer of state/applications.json.

This is the loop that closes the feedback: deep-eval scores are self-assessment,
`apply.py stats --by-version` is the real signal about which resume version
survives the screen.

Subcommands:
  mark       Record an application (usually right after tailoring a resume).
  stage      Move an application to a new stage / close it out.
  list       Human-readable table (or --json).
  followups  Applications that need chasing (silent too long, or action due).
  stats      Funnel counts overall and per resume version.
"""
import argparse
import json
import sys
from datetime import date, datetime

# 顺序即漏斗深度；"简历通过"及以上视为过了简历筛。
STAGES = ["已投递", "简历通过", "笔试", "一面", "二面", "三面", "HR面", "offer"]
CLOSED_STAGES = {"offer", "挂了", "放弃"}
SCREEN_PASSED_INDEX = 1

EMPTY_STORE = {"schema_version": 1, "updated_at": None, "applications": {}}


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_store(path, store):
    store["updated_at"] = datetime.now().astimezone().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_store(path):
    return load_json(path, json.loads(json.dumps(EMPTY_STORE)))


def days_since(stamp):
    try:
        return (date.today() - date.fromisoformat(str(stamp)[:10])).days
    except (ValueError, TypeError):
        return 0


def stage_index(stage):
    return STAGES.index(stage) if stage in STAGES else -1


def resolve_posting(state_path, posting_id):
    state = load_json(state_path, {"postings": {}})
    return state.get("postings", {}).get(posting_id)


def cmd_mark(args):
    store = load_store(args.applications)
    apps = store.setdefault("applications", {})

    company, title, deadline = args.company, args.title, None
    if args.posting_id:
        if not args.state:
            raise SystemExit("mark: 用 --posting-id 时必须同时给 --state")
        rec = resolve_posting(args.state, args.posting_id)
        if rec is None:
            raise SystemExit(f"mark: state 里找不到岗位 {args.posting_id}")
        company = company or rec.get("company")
        title = title or rec.get("title")
        deadline = rec.get("deadline")
    if not company or not title:
        raise SystemExit("mark: 需要 --posting-id，或同时给 --company 和 --title")

    app_id = args.posting_id or f"manual-{date.today().isoformat()}-{len(apps) + 1}"
    if app_id in apps and not args.force:
        raise SystemExit(f"mark: {company} · {title} 已记录过投递（用 --force 覆盖）")

    applied_at = args.date or date.today().isoformat()
    apps[app_id] = {
        "id": app_id,
        "posting_id": args.posting_id or None,
        "company": company,
        "title": title,
        "resume_version": args.resume_version or "",
        "channel": args.channel or "",
        "applied_at": applied_at,
        "deadline": deadline,
        "stage": "已投递",
        "stage_history": [{"stage": "已投递", "date": applied_at, "note": args.note or ""}],
        "next_action_at": args.next_action or None,
        "closed": False,
        "notes": args.note or "",
    }
    save_store(args.applications, store)
    print(f"已记录投递：{company} · {title}（版本 {args.resume_version or '未注明'}，{applied_at}）")


def cmd_stage(args):
    store = load_store(args.applications)
    apps = store.get("applications", {})
    app = apps.get(args.id)
    if app is None:
        matches = [a for a in apps.values() if args.id in (a.get("company", "") + a.get("title", ""))]
        if len(matches) == 1:
            app = matches[0]
        elif len(matches) > 1:
            raise SystemExit("stage: 匹配到多条，请用准确的 id：\n" +
                             "\n".join(f"  {a['id']}  {a['company']} · {a['title']}" for a in matches))
        else:
            raise SystemExit(f"stage: 找不到投递记录 {args.id}")

    when = args.date or date.today().isoformat()
    app["stage"] = args.stage
    app.setdefault("stage_history", []).append(
        {"stage": args.stage, "date": when, "note": args.note or ""})
    app["closed"] = args.stage in CLOSED_STAGES
    app["next_action_at"] = args.next_action or None
    if args.stage in CLOSED_STAGES:
        app["outcome"] = args.stage
    save_store(args.applications, store)
    tail = f"，下一步 {args.next_action}" if args.next_action else ""
    print(f"{app['company']} · {app['title']} → {args.stage}（{when}）{tail}")


def rows(store, open_only=False):
    out = []
    for app in store.get("applications", {}).values():
        if open_only and app.get("closed"):
            continue
        out.append(app)
    out.sort(key=lambda a: a.get("applied_at", ""), reverse=True)
    return out


def cmd_list(args):
    store = load_store(args.applications)
    data = rows(store, args.open_only)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not data:
        print("（还没有投递记录）")
        return
    for a in data:
        age = days_since(a.get("applied_at"))
        line = f"- [{a['id']}] {a['company']} · {a['title']} — {a['stage']}（投于 {a.get('applied_at')}，{age} 天前）"
        if a.get("resume_version"):
            line += f" · 版本 {a['resume_version']}"
        if a.get("next_action_at"):
            line += f" · 下一步 {a['next_action_at']}"
        print(line)


def collect_followups(store, config):
    """Return (silent, due) — silent too long, and next-action due/overdue."""
    followup_days = config.get("applications", {}).get("followup_days", 14)
    stale_days = config.get("applications", {}).get("stale_days", 30)
    today = date.today().isoformat()
    silent, due = [], []
    for a in store.get("applications", {}).values():
        if a.get("closed"):
            continue
        if a.get("next_action_at") and str(a["next_action_at"])[:10] <= today:
            due.append(a)
            continue
        last = (a.get("stage_history") or [{}])[-1].get("date") or a.get("applied_at")
        age = days_since(last)
        if a.get("stage") == "已投递" and age >= followup_days:
            silent.append({**a, "_silent_days": age, "_stale": age >= stale_days})
    silent.sort(key=lambda a: -a["_silent_days"])
    due.sort(key=lambda a: str(a.get("next_action_at")))
    return silent, due


def cmd_followups(args):
    store = load_store(args.applications)
    config = load_json(args.config, {}) if args.config else {}
    silent, due = collect_followups(store, config)
    if args.json:
        print(json.dumps({"silent": silent, "due": due}, ensure_ascii=False, indent=2))
        return
    if not silent and not due:
        print("（暂无需要跟进的投递）")
        return
    for a in due:
        print(f"- 待办到期：{a['company']} · {a['title']} — {a['stage']}，安排在 {a['next_action_at']}")
    for a in silent:
        tag = "疑似已挂，可考虑放弃" if a["_stale"] else "可以催一下 / 找内推问进度"
        print(f"- 已投 {a['_silent_days']} 天无进展：{a['company']} · {a['title']}（{tag}）")


def cmd_stats(args):
    store = load_store(args.applications)
    apps = list(store.get("applications", {}).values())
    if not apps:
        print("（还没有投递记录）")
        return

    def funnel(subset):
        total = len(subset)
        passed = sum(1 for a in subset if stage_index(a.get("stage", "")) >= SCREEN_PASSED_INDEX
                     or a.get("stage") == "offer")
        offers = sum(1 for a in subset if a.get("stage") == "offer")
        rejected = sum(1 for a in subset if a.get("stage") == "挂了")
        rate = f"{passed / total * 100:.0f}%" if total else "—"
        return total, passed, rate, offers, rejected

    total, passed, rate, offers, rejected = funnel(apps)
    print(f"总投递 {total} · 过简历筛 {passed}（{rate}）· offer {offers} · 明确挂了 {rejected}")

    if args.by_version:
        by = {}
        for a in apps:
            by.setdefault(a.get("resume_version") or "（未注明版本）", []).append(a)
        print("\n按简历版本：")
        for version, subset in sorted(by.items(), key=lambda kv: -len(kv[1])):
            t, p, r, o, _ = funnel(subset)
            print(f"- {version}：投 {t} · 过筛 {p}（{r}）· offer {o}")
        if len(by) > 1:
            print("（样本少时这个比例只能当参考，别当结论。）")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("mark")
    p.add_argument("--applications", required=True)
    p.add_argument("--state")
    p.add_argument("--posting-id")
    p.add_argument("--company")
    p.add_argument("--title")
    p.add_argument("--resume-version")
    p.add_argument("--channel")
    p.add_argument("--date")
    p.add_argument("--next-action")
    p.add_argument("--note")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_mark)

    p = sub.add_parser("stage")
    p.add_argument("--applications", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--stage", required=True,
                   help="已投递/简历通过/笔试/一面/二面/三面/HR面/offer/挂了/放弃")
    p.add_argument("--date")
    p.add_argument("--next-action")
    p.add_argument("--note")
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser("list")
    p.add_argument("--applications", required=True)
    p.add_argument("--open-only", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("followups")
    p.add_argument("--applications", required=True)
    p.add_argument("--config")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_followups)

    p = sub.add_parser("stats")
    p.add_argument("--applications", required=True)
    p.add_argument("--by-version", action="store_true")
    p.set_defaults(func=cmd_stats)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
