#!/usr/bin/env python3
"""Render the daily digest as Markdown.

Usage:
  python3 digest.py render --new new_only.json --state state/seen_postings.json \
      --config config.json [--date 2026-07-08] \
      [--evaluated evaluated.json] [--resumes resumes_dir]

The digest title is built from config.json's target_season_label and
job_category_label, so it stays generic across whatever job category the
skill is configured to track (finance is just the default example).

v2: when --resumes is given, each posting carries its deep-eval match block
(score/pros/gaps from state) and deep-eval statistics; --evaluated additionally
renders the "backfilled evaluations" section for previously-pending postings.
Without the new flags the output stays v1-compatible (no match lines).

Prints a Markdown digest to stdout.
"""
import argparse
import json
import os
from collections import OrderedDict
from datetime import date

# 分档常量 —— 与 references/matching.md 严格一致
SCORE_TIERS = [
    (85, "高度匹配"),
    (70, "推荐投递"),
    (50, "备选"),
    (0, "观望"),
]


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def tier_label(score):
    for threshold, label in SCORE_TIERS:
        if score >= threshold:
            return label
    return "观望"


def match_of(rec, state):
    posting = state.get("postings", {}).get(rec.get("id", ""))
    if posting is None:
        return rec.get("match")
    return posting.get("match")


def score_of(rec, state):
    m = match_of(rec, state)
    if m and m.get("status") == "scored" and m.get("score") is not None:
        return m["score"]
    return -1


def match_lines(rec, state, min_score_for_action):
    m = match_of(rec, state)
    if not m:
        return []
    status = m.get("status")
    if status == "scored" and m.get("score") is not None:
        score = m["score"]
        line = f"  匹配：{score}/100 · {tier_label(score)}"
        if score >= min_score_for_action:
            line += " · 建议一键定制简历"
        lines = [line]
        if m.get("pros"):
            lines.append(f"  优势：{m['pros']}")
        if m.get("gaps"):
            lines.append(f"  差距：{m['gaps']}")
        return lines
    if status == "jd_unavailable":
        return ["  匹配：JD未抓到，未评分"]
    return ["  匹配：待深评（下次运行自动补评）"]


def match_stats(postings_iter):
    scored = pending = 0
    for rec in postings_iter:
        m = rec.get("match")
        if m and m.get("status") == "scored":
            scored += 1
        elif m is None or m.get("status") == "pending":
            pending += 1
    return scored, pending


def resume_missing(resumes_dir):
    index = load_json(os.path.join(resumes_dir, "index.json"), None)
    return index is None or not index.get("active_base")


def group_by_company(postings):
    grouped = OrderedDict()
    for rec in postings:
        grouped.setdefault(rec["company"], []).append(rec)
    return grouped


def render_markdown(new_postings, state, today, season_label, category_label,
                    config=None, evaluated=None, resumes_dir=None):
    config = config or {}
    v2 = resumes_dir is not None or evaluated is not None
    min_score_for_action = config.get("resume", {}).get("min_score_for_action", 70)
    resume_enabled = config.get("resume", {}).get("enabled", True)

    prefix = f"{season_label} " if season_label else ""
    direction = f"{category_label}方向" if category_label else ""
    title = f"{prefix}{direction}岗位监控日报"

    lines = []
    hint_lines = []
    no_resume = v2 and resumes_dir is not None and resume_enabled and resume_missing(resumes_dir)
    if no_resume:
        hint_lines.append("> 提示：尚未导入简历，本报告未做匹配评分。下次对话时把简历文件发给我即可开启匹配功能。")
    show_match = v2 and resume_enabled and not no_resume

    new_ids = {r.get("id") for r in new_postings}
    backfilled = []
    if evaluated:
        backfilled = [e for e in evaluated
                      if e.get("fetched") and e.get("id") not in new_ids]

    def backfill_section():
        if not backfilled:
            return
        lines.append("## 本次补评完成（此前\"待深评\"岗位）")
        for e in backfilled:
            posting = state.get("postings", {}).get(e.get("id"), {})
            company = posting.get("company", "未知公司")
            job_title = posting.get("title", "未知岗位")
            lines.append(f"- {company} · {job_title} — {e.get('score', '?')}/100，优势：{e.get('pros', '')}")
        lines.append("")

    def footer_stats():
        companies = {r["company"] for r in state.get("postings", {}).values()}
        total = len(state.get("postings", {}))
        base = f"当前已监控 {len(companies)} 家公司 / {total} 个历史岗位"
        if v2:
            scored, pending = match_stats(state.get("postings", {}).values())
            base += f" · 已深评 {scored} · 待深评 {pending}"
        return base + "。"

    if not new_postings:
        lines.append(f"# {title} · {today}")
        lines.append("")
        lines.extend(hint_lines)
        if hint_lines:
            lines.append("")
        no_new = f"今日未发现新的{category_label}方向正式校招岗位。" if category_label else "今日未发现新的正式校招岗位。"
        lines.append(no_new)
        lines.append(footer_stats())
        if backfilled:
            lines.append("")
            backfill_section()
        return "\n".join(lines).rstrip()

    if show_match:
        company_max = {}
        for r in new_postings:
            s = score_of(r, state)
            company_max[r["company"]] = max(company_max.get(r["company"], -1), s)
        new_postings = sorted(
            new_postings,
            key=lambda r: (-company_max[r["company"]], r["company"],
                           -score_of(r, state), r.get("title", "")),
        )

    grouped = group_by_company(new_postings)
    n_companies = len(grouped)
    n_postings = len(new_postings)

    lines.append(f"# {title} · {today}")
    lines.append("")
    lines.extend(hint_lines)
    if hint_lines:
        lines.append("")
    header = f"发现 {n_companies} 家新开放企业，共 {n_postings} 个新增岗位"
    if show_match:
        scored, pending = match_stats(
            state.get("postings", {}).get(r.get("id"), r) for r in new_postings)
        header += f"（已深评 {scored}，待深评 {pending}）"
    lines.append(header)
    lines.append("")
    for company, recs in grouped.items():
        lines.append(f"## {company}")
        for r in recs:
            lines.append(f"- **{r['title']}** — {r.get('city', '未注明')}")
            if show_match:
                lines.extend(match_lines(r, state, min_score_for_action))
            if r.get("highlight"):
                lines.append(f"  亮点：{r['highlight']}")
            lines.append(f"  链接：{r.get('source_url', '')}")
            lines.append(f"  来源：{r.get('source_platform', '')} · 发现于 {r.get('first_seen', today)}")
        lines.append("")
    backfill_section()
    if v2:
        lines.append(footer_stats())
    return "\n".join(lines).rstrip()


def cmd_render(args):
    new_postings = load_json(args.new, [])
    state = load_json(args.state, {"postings": {}})
    config = load_json(args.config, {})
    evaluated = load_json(args.evaluated, []) if args.evaluated else None
    today = args.date or date.today().isoformat()
    season_label = config.get("target_season_label", "")
    category_label = config.get("job_category_label", "")
    print(render_markdown(new_postings, state, today, season_label, category_label,
                          config=config, evaluated=evaluated, resumes_dir=args.resumes))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render")
    p_render.add_argument("--new", required=True)
    p_render.add_argument("--state", required=True)
    p_render.add_argument("--config", required=True)
    p_render.add_argument("--date")
    p_render.add_argument("--evaluated")
    p_render.add_argument("--resumes")
    p_render.set_defaults(func=cmd_render)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
