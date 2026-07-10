#!/usr/bin/env python3
"""Render the daily digest as Markdown.

Usage:
  python3 digest.py render --new new_only.json --state state/seen_postings.json \
      --config config.json [--date 2026-07-08]

The digest title is built from config.json's target_season_label and
job_category_label, so it stays generic across whatever job category the
skill is configured to track (finance is just the default example).

Prints a Markdown digest to stdout.
"""
import argparse
import json
from collections import OrderedDict
from datetime import date


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def group_by_company(postings):
    grouped = OrderedDict()
    for rec in postings:
        grouped.setdefault(rec["company"], []).append(rec)
    return grouped


def render_markdown(new_postings, state, today, season_label, category_label):
    prefix = f"{season_label} " if season_label else ""
    direction = f"{category_label}方向" if category_label else ""
    title = f"{prefix}{direction}岗位监控日报"

    lines = []
    if not new_postings:
        companies = {r["company"] for r in state.get("postings", {}).values()}
        total = len(state.get("postings", {}))
        lines.append(f"# {title} · {today}")
        lines.append("")
        no_new = f"今日未发现新的{category_label}方向正式校招岗位。" if category_label else "今日未发现新的正式校招岗位。"
        lines.append(no_new)
        lines.append(f"当前已监控 {len(companies)} 家公司 / {total} 个历史岗位。")
        return "\n".join(lines)

    grouped = group_by_company(new_postings)
    n_companies = len(grouped)
    n_postings = len(new_postings)

    lines.append(f"# {title} · {today}")
    lines.append("")
    lines.append(f"发现 {n_companies} 家新开放企业，共 {n_postings} 个新增岗位")
    lines.append("")
    for company, recs in grouped.items():
        lines.append(f"## {company}")
        for r in recs:
            lines.append(f"- **{r['title']}** — {r.get('city', '未注明')}")
            if r.get("highlight"):
                lines.append(f"  亮点：{r['highlight']}")
            lines.append(f"  链接：{r.get('source_url', '')}")
            lines.append(f"  来源：{r.get('source_platform', '')} · 发现于 {r.get('first_seen', today)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def cmd_render(args):
    new_postings = load_json(args.new, [])
    state = load_json(args.state, {"postings": {}})
    config = load_json(args.config, {})
    today = args.date or date.today().isoformat()
    season_label = config.get("target_season_label", "")
    category_label = config.get("job_category_label", "")
    print(render_markdown(new_postings, state, today, season_label, category_label))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    p_render = sub.add_parser("render")
    p_render.add_argument("--new", required=True)
    p_render.add_argument("--state", required=True)
    p_render.add_argument("--config", required=True)
    p_render.add_argument("--date")
    p_render.set_defaults(func=cmd_render)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()