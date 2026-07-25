#!/usr/bin/env python3
"""Plan the discovery layer for one run, and commit its bookkeeping afterwards.

Everything deterministic about "which lanes run today" lives here so the
orchestrator never has to reason about rotation, cursors or yield history.

Subcommands:
  plan             Decide today's lanes + watchlist batch + known-company hint.
  commit           Advance cursors, record the sweep, update per-lane yield.
  known-companies  Print the already-tracked company list on its own.
  yield-report     One-line-per-lane yield summary (used by the digest).

Lean mode (default): only the two 公众号 lanes run daily; the aggregator lanes
run on one full sweep day per week. The first run ever is always a full sweep
so the initial backlog gets picked up.
"""
import argparse
import json
from datetime import date, datetime, timedelta

# 车道定义。tier="daily" 每天跑；tier="full" 只在全量日跑。
# channel 决定用哪个模型（config.discovery.agent_model 里按 channel 取）。
LANES = [
    {
        "id": "wechat-launch",
        "name": "公众号-新启动公告扫描",
        "tier": "daily",
        "channel": "wechat",
        "scope_hint": "最多深入核实 10-15 家最相关的公司，覆盖面比逐一核实的精确度更重要",
    },
    {
        "id": "wechat-watchlist",
        "name": "公众号-公司池轮询",
        "tier": "daily",
        "channel": "wechat",
        "scope_hint": "只查本轮批次里列出的公司，不要自行扩展名单",
    },
    {
        "id": "roundup-newcompany",
        "name": "汇总帖挖新公司→公众号核实→官网",
        "tier": "full",
        "channel": "aggregator",
        "scope_hint": "最多深入核实 12 家与目标方向最相关的公司",
    },
    {
        "id": "aggregator-nowcoder",
        "name": "牛客网校招板块",
        "tier": "full",
        "channel": "aggregator",
        "scope_hint": "最多深入核实 10-15 家最相关的公司",
    },
    {
        "id": "aggregator-campus",
        "name": "51job校园+智联校园+猎聘校园",
        "tier": "full",
        "channel": "aggregator",
        "scope_hint": "三个站点合计最多深入核实 10-15 家最相关的公司",
    },
    {
        "id": "aggregator-intern",
        "name": "实习僧",
        "tier": "full",
        "channel": "aggregator",
        "requires_internships": True,
        "scope_hint": "最多深入核实 10 家最相关的公司",
    },
]

EMPTY_YIELD = {"runs": 0, "new": 0, "hit": 0, "last_new": None, "zero_streak": 0}


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


def lane_by_id(lane_id):
    for lane in LANES:
        if lane["id"] == lane_id:
            return lane
    return None


def known_companies(state, limit):
    """Companies already in state, most-recently-confirmed first."""
    seen = {}
    for rec in state.get("postings", {}).values():
        company = (rec.get("company") or "").strip()
        if not company:
            continue
        stamp = rec.get("last_confirmed") or rec.get("first_seen") or ""
        if stamp > seen.get(company, ""):
            seen[company] = stamp
    ordered = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)
    names = [c for c, _ in ordered]
    return names[:limit], len(names) > limit


def decide_sweep(config, state, today, force):
    """Return (sweep, reason). sweep is "full" or "lean"."""
    discovery = config.get("discovery", {})
    if force in ("full", "lean"):
        return force, f"由 --force {force} 指定"
    if discovery.get("mode") == "full_daily":
        return "full", "config.discovery.mode = full_daily，每天全量"

    last = state.get("last_full_sweep")
    if not last:
        return "full", "首次运行（尚无全量记录），先铺一次全量底子"

    try:
        last_date = date.fromisoformat(last)
    except (ValueError, TypeError):
        return "full", "last_full_sweep 无法解析，按全量处理"

    gap = (today - last_date).days
    if gap >= 7:
        return "full", f"距上次全量已 {gap} 天，触发补漏全量"

    target_weekday = discovery.get("full_sweep_weekday", 6)
    if today.weekday() == target_weekday and gap >= 1:
        return "full", f"今天是每周全量日（周{'一二三四五六日'[target_weekday]}）"

    days_ahead = (target_weekday - today.weekday()) % 7 or 7
    next_full = today + timedelta(days=days_ahead)
    return "lean", f"精简日（上次全量 {last} · 下次全量 {next_full.isoformat()}）"


def cmd_plan(args):
    config = load_json(args.config, {})
    state = load_json(args.state, {"postings": {}})
    discovery = config.get("discovery", {})
    today = date.fromisoformat(args.date) if args.date else date.today()

    sweep, reason = decide_sweep(config, state, today, args.force)
    include_internships = bool(config.get("include_internships"))
    disabled = set(discovery.get("disabled_lanes", []) or [])
    demote_after = discovery.get("auto_demote_after_zero_runs", 6)
    yields = state.get("source_yield", {})

    models = discovery.get("agent_model", {}) or {}
    watchlist = discovery.get("company_watchlist", []) or []
    batch_size = discovery.get("watchlist_batch_size", 12)
    cursor = int(state.get("wechat_rotation_cursor", 0) or 0)

    lanes, skipped, demoted = [], [], []
    for lane in LANES:
        if lane["id"] in disabled:
            skipped.append({"id": lane["id"], "why": "已被 config.discovery.disabled_lanes 禁用"})
            continue
        if lane.get("requires_internships") and not include_internships:
            skipped.append({"id": lane["id"], "why": "include_internships 为 false，该来源产出会被全量过滤掉"})
            continue
        if lane["tier"] == "full" and sweep != "full":
            skipped.append({"id": lane["id"], "why": "精简日不跑聚合平台，等全量日"})
            continue

        # 自动降频只在精简日生效；全量日就是用来补漏的，一律跑满。
        streak = int(yields.get(lane["id"], {}).get("zero_streak", 0) or 0)
        if sweep != "full" and demote_after and streak >= demote_after:
            demoted.append({"id": lane["id"], "zero_streak": streak})
            skipped.append({"id": lane["id"], "why": f"连续 {streak} 次零产出，已自动降频（下次全量日仍会跑）"})
            continue

        entry = {
            "id": lane["id"],
            "name": lane["name"],
            "model": models.get(lane["channel"], ""),
            "scope_hint": lane["scope_hint"],
        }
        if lane["id"] == "wechat-watchlist":
            if not watchlist:
                skipped.append({"id": lane["id"], "why": "company_watchlist 为空，初始化时未生成"})
                continue
            start = cursor % len(watchlist)
            batch = (watchlist + watchlist)[start:start + min(batch_size, len(watchlist))]
            entry["batch"] = batch
            entry["batch_range"] = f"{start + 1}-{start + len(batch)} / 共 {len(watchlist)} 家"
        lanes.append(entry)

    names, truncated = known_companies(state, discovery.get("known_company_hint_max", 200))
    plan = {
        "date": today.isoformat(),
        "sweep": sweep,
        "sweep_reason": reason,
        "lanes": lanes,
        "skipped": skipped,
        "auto_demoted": demoted,
        "known_companies": names,
        "known_companies_truncated": truncated,
        "next_cursor": (cursor + batch_size) % len(watchlist) if watchlist else 0,
    }
    save_json(args.output, plan)

    lane_desc = "、".join(l["name"] for l in lanes) or "（无）"
    print(f"[{today.isoformat()}] {sweep} 模式：{reason}")
    print(f"本次发现 {len(lanes)} 路：{lane_desc}")
    if demoted:
        print("自动降频：" + "、".join(f"{d['id']}(连续{d['zero_streak']}次零产出)" for d in demoted))
    print(f"已监控公司提示 {len(names)} 家" + ("（已截断）" if truncated else ""))


def cmd_commit(args):
    config = load_json(args.config, {})
    state = load_json(args.state, {"postings": {}})
    plan = load_json(args.plan, {})
    if not plan:
        raise SystemExit("commit: 读不到 plan 文件，先跑 discovery.py plan")

    yields = state.setdefault("source_yield", {})
    # dedupe.py 把本次每路新增数暂存在这里，commit 消费后清掉。
    run_new = state.pop("_last_run_lane_new", {}) or {}

    for lane in plan.get("lanes", []):
        entry = yields.setdefault(lane["id"], dict(EMPTY_YIELD))
        entry["runs"] = int(entry.get("runs", 0)) + 1
        gained = int(run_new.get(lane["id"], 0))
        if gained:
            entry["new"] = int(entry.get("new", 0)) + gained
            entry["last_new"] = plan.get("date")
            entry["zero_streak"] = 0
        else:
            entry["zero_streak"] = int(entry.get("zero_streak", 0)) + 1

    if plan.get("sweep") == "full":
        state["last_full_sweep"] = plan.get("date")
    if any(l["id"] == "wechat-watchlist" for l in plan.get("lanes", [])):
        state["wechat_rotation_cursor"] = plan.get("next_cursor", 0)

    save_json(args.state, state)
    print(json.dumps({
        "sweep": plan.get("sweep"),
        "lanes_run": [l["id"] for l in plan.get("lanes", [])],
        "new_by_lane": run_new,
        "wechat_rotation_cursor": state.get("wechat_rotation_cursor", 0),
        "last_full_sweep": state.get("last_full_sweep"),
    }, ensure_ascii=False))


def cmd_known_companies(args):
    config = load_json(args.config, {})
    state = load_json(args.state, {"postings": {}})
    limit = config.get("discovery", {}).get("known_company_hint_max", 200)
    names, truncated = known_companies(state, limit)
    print("、".join(names) if names else "（暂无已监控公司）")
    if truncated:
        print(f"（仅列出最近确认的 {limit} 家）")


def cmd_yield_report(args):
    state = load_json(args.state, {"postings": {}})
    yields = state.get("source_yield", {})
    if not yields:
        print("（暂无来源产出统计）")
        return
    rows = sorted(yields.items(), key=lambda kv: -int(kv[1].get("new", 0)))
    for lane_id, y in rows:
        lane = lane_by_id(lane_id)
        name = lane["name"] if lane else lane_id
        runs = y.get("runs", 0)
        per_run = (y.get("new", 0) / runs) if runs else 0
        line = f"- {name}：跑 {runs} 次 / 新增 {y.get('new', 0)} 条（{per_run:.1f} 条每次）/ 高分 {y.get('hit', 0)} 条"
        if y.get("zero_streak"):
            line += f" · 连续 {y['zero_streak']} 次零产出"
        print(line)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--config", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--date")
    p.add_argument("--force", choices=["full", "lean"])
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("commit")
    p.add_argument("--config", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--plan", required=True)
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("known-companies")
    p.add_argument("--config", required=True)
    p.add_argument("--state", required=True)
    p.set_defaults(func=cmd_known_companies)

    p = sub.add_parser("yield-report")
    p.add_argument("--state", required=True)
    p.set_defaults(func=cmd_yield_report)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
