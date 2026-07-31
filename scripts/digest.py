#!/usr/bin/env python3
"""Render the five-section daily job digest from SQLite."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    from db import connect, now_iso, json_loads
except ImportError:  # pragma: no cover - package execution
    from .db import connect, now_iso, json_loads


def _source_fields(row):
    return (
        row["source_tier"] or "C",
        row["official_verified_at"] or "未核实",
    )


def _recommendation_card(row):
    evidence = json_loads(row["evidence_json"], [])
    gaps = json_loads(row["gaps_json"], [])
    actions = json_loads(row["actions_json"], [])
    tier, verified = _source_fields(row)
    evidence_text = "；".join(str(item) for item in evidence[:3]) or "暂无评分证据"
    gap_text = "；".join(
        str(item.get("text", item)) if isinstance(item, dict) else str(item)
        for item in gaps[:2]
    ) or "暂无记录"
    action_text = "；".join(str(item) for item in actions[:3]) or "先核对 JD 和投递条件"
    return [
        f"### {row['company']} · {row['title']}",
        f"- 城市：{row['city']}；来源等级：{tier}；官方核实：{verified}",
        f"- 匹配度：{row['score']}；置信度：{row['confidence']}；截止：{row['deadline'] or '未注明'}",
        f"- 最强匹配证据：{evidence_text}",
        f"- 最大缺口：{gap_text}",
        f"- 建议修改：{action_text}",
        f"- 官方投递链接：{row['application_url'] or '暂无官方链接'}",
        f"- 操作：定制简历 `posting={row['posting_id']}`；填写网申 `posting={row['posting_id']}`；归档 `jobctl.py posting archive {row['posting_id']}`",
        "",
    ]


def _application_card(row, now):
    try:
        last_update = datetime.fromisoformat(row["last_update_at"])
        current = datetime.fromisoformat(now)
        elapsed_days = max(0, (current.date() - last_update.date()).days)
    except (TypeError, ValueError):
        elapsed_days = "未知"
    due_kind = (
        "状态检查"
        if row["current_stage"] in {"已投递", "筛选中"}
        else "投递待办"
    )
    return [
        f"### {row['company']} · {row['title']}",
        f"- 投递日期：{row['applied_at']}；当前阶段：{row['current_stage']}",
        f"- {due_kind}时间：{row['next_action_at']}；距上次更新：{elapsed_days} 天",
        f"- 申请入口：{row['application_url'] or '暂无可用链接'}",
        f"- 已查看但暂无更新：`jobctl.py application check-status --id {row['id']} --result no-update`",
        f"- 状态已更新：`jobctl.py application check-status --id {row['id']} --result updated --stage <新阶段>`",
        f"- 停止状态提醒：`jobctl.py application check-status --id {row['id']} --result stop`",
        "",
    ]


def render(args):
    conn = connect(args.data_dir)
    campaign = (
        conn.execute("SELECT * FROM campaigns WHERE id=?", (args.campaign,)).fetchone()
        if args.campaign
        else conn.execute("SELECT * FROM campaigns WHERE active=1 LIMIT 1").fetchone()
    )
    if campaign is None:
        print("# Job Copilot 日报\n\n尚未建立 active Campaign。请先完成路径选择和简历初始化。")
        conn.close()
        return

    now = now_iso()
    campaign_id = campaign["id"]
    due = conn.execute(
        """SELECT r.*,p.company,p.title,p.city,p.deadline,p.application_url,m.score,m.confidence,
           m.evidence_json,m.gaps_json,m.actions_json,
           COALESCE(MIN(s.tier),'C') AS source_tier,MAX(s.verified_at) AS official_verified_at
           FROM recommendations r JOIN postings p ON p.id=r.posting_id
           LEFT JOIN matches m ON m.id=r.match_id LEFT JOIN posting_sources s ON s.posting_id=p.id
           WHERE r.campaign_id=? AND r.status IN ('pending','preparing','snoozed')
             AND r.decision_due_at<=? AND p.status='active'
             AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.posting_id=p.id)
             AND (p.deadline IS NULL OR substr(p.deadline,1,10)>=date('now'))
           GROUP BY r.id ORDER BY r.decision_due_at""",
        (campaign_id, now),
    ).fetchall()
    today = conn.execute(
        """SELECT r.*,p.company,p.title,p.city,p.deadline,p.application_url,m.score,m.confidence,
           m.evidence_json,m.gaps_json,m.actions_json,
           COALESCE(MIN(s.tier),'C') AS source_tier,MAX(s.verified_at) AS official_verified_at
           FROM recommendations r JOIN postings p ON p.id=r.posting_id
           LEFT JOIN matches m ON m.id=r.match_id LEFT JOIN posting_sources s ON s.posting_id=p.id
           WHERE r.campaign_id=? AND r.status IN ('pending','preparing')
             AND r.recommended_at>=date('now','-1 day') AND p.status='active'
             AND (p.deadline IS NULL OR substr(p.deadline,1,10)>=date('now'))
             AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.posting_id=p.id)
           GROUP BY r.id ORDER BY COALESCE(m.score,0) DESC LIMIT ?""",
        (campaign_id, int(campaign["daily_quota"])),
    ).fetchall()
    unverified = conn.execute(
        """SELECT p.id,p.company,p.title,p.city,p.application_url,p.first_seen_at,
           COALESCE(MIN(s.tier),'C') AS source_tier
           FROM postings p LEFT JOIN posting_sources s ON s.posting_id=p.id
           WHERE p.campaign_id=? AND p.status='active'
           GROUP BY p.id HAVING source_tier='C'
           ORDER BY p.first_seen_at DESC LIMIT 20""",
        (campaign_id,),
    ).fetchall()
    apps = conn.execute(
        """SELECT a.*,p.company,p.title,p.application_url
           FROM applications a JOIN postings p ON p.id=a.posting_id
           JOIN campaigns c ON c.id=p.campaign_id
           WHERE c.id=? AND a.closed=0 AND a.next_action_at IS NOT NULL
             AND a.next_action_at<=? ORDER BY a.next_action_at""",
        (campaign_id, now),
    ).fetchall()
    latest_run = conn.execute(
        "SELECT * FROM discovery_runs WHERE campaign_id=? ORDER BY completed_at DESC LIMIT 1",
        (campaign_id,),
    ).fetchone()

    lines = [
        f"# Job Copilot 日报 · {datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')}",
        "",
        f"Campaign：{campaign['name']}（{'校招' if campaign['route']=='campus' else '社招'}）",
        "",
        "## 一、昨天岗位待决策",
        "",
    ]
    if not due:
        lines.append("暂无超过 24 小时未处理的推荐。")
    else:
        for row in due:
            lines.append(
                f"- **{row['company']} · {row['title']}**（{row['city']}，匹配 {row['score'] or '未评分'}，置信度 {row['confidence'] or '未知'}）"
            )
            lines.append(
                f"  - 请选择：归档 `jobctl.py due archive {row['id']}`；保留到下一次日报 `jobctl.py due snooze {row['id']}`"
            )

    lines += ["", "## 二、投递待跟进", ""]
    if not apps:
        lines.append("暂无到期的笔试、面试或其他投递待办。")
    else:
        for row in apps:
            lines.extend(_application_card(row, now))

    lines += ["", "## 三、今日高匹配岗位", ""]
    if not today:
        lines.append("今天没有新增的正式推荐；可能仍在核实来源或等待 JD。")
    else:
        for row in today:
            lines.extend(_recommendation_card(row))

    lines += ["## 四、待核实岗位", ""]
    if not unverified:
        lines.append("暂无 C 级待核实岗位。")
    else:
        lines.extend(
            f"- {row['company']} · {row['title']}（{row['city']}）：尚未回到官方渠道核实，不占今日配额；来源等级 {row['source_tier']}。"
            for row in unverified
        )

    lines += ["", "## 五、今日来源与运行说明", ""]
    if latest_run is None:
        lines.append("尚未运行岗位发现。")
    else:
        lanes = json_loads(latest_run["lanes_json"], [])
        lane_names = ", ".join(item.get("lane_id", "") for item in lanes if isinstance(item, dict)) or "无"
        errors = json_loads(latest_run["error_json"], [])
        lines.append(f"最近运行：{latest_run['completed_at']}；候选数：{latest_run['result_count']}；车道：{lane_names}。")
        if errors:
            lines.append(f"运行错误：{'; '.join(str(item) for item in errors[:3])}。")
        else:
            lines.append("来源策略：官网与官方公众号优先；聚合平台低频补漏；C 级岗位不进入正式推荐配额。")

    lines += [
        "",
        "提示：匹配分只代表当前简历证据与 JD 的对应度，不代表录用概率。网申草稿不等于已投递；提交后请告诉我。",
        "不要把密码、验证码、身份证号发给 Skill。用户不回答归档/保留问题时，下次日报继续展示，不自动删除。",
    ]
    print("\n".join(lines))
    conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--campaign")
    ap.add_argument("--data-dir")
    args = ap.parse_args(argv)
    render(args)


if __name__ == "__main__":
    main()
