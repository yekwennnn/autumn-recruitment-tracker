#!/usr/bin/env python3
"""User-facing state CLI for job-copilot.

The AI layer produces validated JSON; this file is the only writer for the
SQLite state.  Commands are deliberately small and idempotent so a weaker
model can execute them without inventing SQL or state transitions.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import shutil
import sys
import uuid
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from db import (
        canonical_key,
        connect,
        data_dir,
        hash_file,
        hash_text,
        hours_from,
        json_dumps,
        json_loads,
        validate_profile_json,
        now_iso,
        normalize_component,
        redact,
        redact_structure,
        row_dict,
        rows_dict,
        save_config,
        load_config,
        transaction,
    )
except ImportError:  # pragma: no cover - supports importing as a package
    from .db import (
        canonical_key,
        connect,
        data_dir,
        hash_file,
        hash_text,
        hours_from,
        json_dumps,
        json_loads,
        validate_profile_json,
        now_iso,
        normalize_component,
        redact,
        redact_structure,
        row_dict,
        rows_dict,
        save_config,
        load_config,
        transaction,
    )


SCRIPT_DIR = Path(__file__).resolve().parent
APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
VALID_ROUTES = {"campus", "social"}
VALID_STAGES = {
    "已投递", "筛选中", "在线测评", "笔试", "HR沟通", "一面", "二面", "终面", "Offer",
    "拒绝", "放弃", "过期", "归档",
}
TERMINAL_STAGES = {"拒绝", "放弃", "过期", "归档"}
SOURCE_TIERS = {"A", "B", "C"}
INTERVIEW_STATUSES = {"started", "in_progress", "completed", "abandoned"}
INTERVIEW_MODES = {"coached"}
INTERVIEW_SCORE_LIMITS = {
    "relevance": 25,
    "evidence": 25,
    "structure": 20,
    "role_fit": 20,
    "clarity": 10,
}
INTERVIEW_FORBIDDEN_KEYS = {
    "answer", "answers", "raw_answer", "response", "responses", "transcript",
    "verbatim", "逐字回答", "回答原文", "完整问答", "润色全文",
}


def emit(value, as_json=False):
    if as_json or isinstance(value, (dict, list)):
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        print(value)


def fail(message, code=2):
    print(f"错误：{redact(message)}", file=sys.stderr)
    raise SystemExit(code)


def parse_json_arg(value, default):
    if value is None:
        return default
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        fail(f"JSON 参数无效：{exc}")
    return parsed


def parse_csv(value):
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def redact_profile_for_output(value):
    """Keep profile inspection useful without printing full contact values."""
    contact_keys = {"phone", "mobile", "tel", "telephone", "email", "e-mail"}
    if isinstance(value, dict):
        return {
            key: redact(str(item)) if str(key).lower() in contact_keys else redact_profile_for_output(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_profile_for_output(item) for item in value]
    return value


def uid(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def require_route(route):
    if route not in VALID_ROUTES:
        fail("route 必须是 campus 或 social")


def get_active_campaign(conn):
    return conn.execute("SELECT * FROM campaigns WHERE active=1 LIMIT 1").fetchone()


def get_or_create_profile(conn, profile_id=None, name_masked="求职者"):
    if profile_id:
        row = conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            fail(f"找不到 profile：{profile_id}")
        return row
    row = conn.execute("SELECT * FROM profiles ORDER BY created_at LIMIT 1").fetchone()
    if row:
        return row
    profile_id = "profile-default"
    stamp = now_iso()
    conn.execute(
        "INSERT INTO profiles(id,name_masked,created_at,updated_at) VALUES(?,?,?,?)",
        (profile_id, name_masked, stamp, stamp),
    )
    return conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()


def normalize_quota(value):
    try:
        quota = int(value)
    except (TypeError, ValueError):
        fail("daily quota 必须是整数")
    if not 1 <= quota <= 20:
        fail("daily quota 必须在 1 到 20 之间")
    return quota


def normalize_score(value):
    try:
        score = int(value)
    except (TypeError, ValueError):
        fail("匹配阈值必须是整数")
    if not 0 <= score <= 100:
        fail("匹配阈值必须在 0 到 100 之间")
    return score


def normalize_iso(value, field_name="时间"):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        fail(f"{field_name} 必须是 ISO 8601 时间")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=APP_TIMEZONE)
    return parsed.isoformat(timespec="seconds")


def _timezone_from_config(config):
    name = str(config.get("timezone") or "Asia/Shanghai")
    try:
        return ZoneInfo(name)
    except Exception as exc:
        raise ValueError(f"配置中的 timezone 无效：{name}") from exc


def _calendar_followup(value, digest_time, days, timezone_name="Asia/Shanghai"):
    try:
        days = int(days)
    except (TypeError, ValueError):
        fail("application follow-up 天数必须是整数")
    if not 1 <= days <= 90:
        fail("application follow-up 天数必须在 1 到 90 之间")
    try:
        timezone_value = ZoneInfo(timezone_name)
        applied = datetime.fromisoformat(value)
        if applied.tzinfo is None:
            applied = applied.replace(tzinfo=timezone_value)
        applied = applied.astimezone(timezone_value)
        hour_text, minute_text = digest_time.split(":", 1)
        digest_clock = time(hour=int(hour_text), minute=int(minute_text))
    except (TypeError, ValueError) as exc:
        fail("投递时间或日报时间格式无效")
    due_date = applied.date() + timedelta(days=days)
    return datetime.combine(due_date, digest_clock, timezone_value).isoformat(timespec="seconds")


def _followup_for_posting(conn, posting_id, base_time, root, days=None):
    row = conn.execute(
        """SELECT c.digest_time
           FROM postings p JOIN campaigns c ON c.id=p.campaign_id
           WHERE p.id=?""",
        (posting_id,),
    ).fetchone()
    if row is None:
        fail(f"找不到岗位：{posting_id}")
    config = load_config(root)
    timezone_value = _timezone_from_config(config)
    interval = days if days is not None else config.get("application_followup_days_default", 3)
    return _calendar_followup(base_time, row["digest_time"], interval, timezone_value.key)


def _validate_score_component(name, value):
    maximum = INTERVIEW_SCORE_LIMITS[name]
    try:
        score = int(value)
    except (TypeError, ValueError):
        fail(f"{name} 分数必须是整数")
    if not 0 <= score <= maximum:
        fail(f"{name} 分数必须在 0 到 {maximum} 之间")
    return score


def _validate_interview_payload(value, label):
    """Allow structured coaching summaries while rejecting transcript-shaped data."""
    try:
        serialized = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        fail(f"{label} 不是有效 JSON：{exc}")
    if len(serialized) > 50000:
        fail(f"{label} 过长")

    def walk(item):
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = str(key).strip().lower()
                if any(forbidden in normalized for forbidden in INTERVIEW_FORBIDDEN_KEYS):
                    fail(f"{label} 不能包含逐字回答字段：{key}")
                walk(nested)
        elif isinstance(item, list):
            for nested in item:
                walk(nested)
        elif not isinstance(item, (str, int, float, bool, type(None))):
            fail(f"{label} 含不支持的数据类型")

    walk(value)
    return value


def _parse_summary_list(value, label):
    parsed = parse_json_arg(value, [])
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        fail(f"{label} 必须是字符串数组")
    if len(parsed) > 20:
        fail(f"{label} 最多保存 20 项")
    cleaned = [redact(item.strip()) for item in parsed if item.strip()]
    if any(len(item) > 1000 for item in cleaned):
        fail(f"{label} 单项不能超过 1000 字")
    return cleaned


def _default_interview_plan(route, round_label, focus, question_count, has_jd):
    if route == "campus":
        categories = [
            ("self_intro_motivation", "自我介绍、求职动机与学习方向"),
            ("project_internship", "项目或实习经历深挖"),
            ("jd_core", "JD 核心能力及迁移证据"),
            ("learning_collaboration", "学习能力、协作、冲突或失败复盘"),
            ("scenario_case", "岗位场景题或业务案例"),
            ("candidate_questions", "反问面试官与收尾表达"),
        ]
    else:
        categories = [
            ("self_intro_motivation", "自我介绍、转岗动机与职业选择"),
            ("achievement_scope", "工作成果、职责边界和指标深挖"),
            ("jd_core", "JD 核心能力及业务证据"),
            ("collaboration_conflict", "跨团队协作、取舍、冲突或失败复盘"),
            ("business_case", "岗位场景、数据判断或业务案例"),
            ("candidate_questions", "反问面试官与收尾表达"),
        ]
    if "HR" in round_label.upper() or "人力" in round_label:
        emphasis = "动机、稳定性、职业规划、到岗时间；薪资等敏感偏好必须先让用户确认"
    elif "终面" in round_label:
        emphasis = "价值观、复杂决策、长期发展和高质量反问"
    else:
        emphasis = f"{focus}能力、事实证据、方法、取舍和复盘"
    while len(categories) < question_count:
        number = len(categories) + 1
        categories.append((f"deep_dive_{number}", "根据上一题证据进行岗位相关追问"))
    return {
        "route": route,
        "round_label": round_label,
        "focus": focus,
        "specificity": "jd_grounded" if has_jd else "limited_without_jd",
        "emphasis": emphasis,
        "categories": [
            {"index": index, "category": category, "purpose": purpose}
            for index, (category, purpose) in enumerate(categories[:question_count], start=1)
        ],
    }


def cmd_init(args):
    root = data_dir(args.data_dir)
    conn = connect(root)
    config = load_config(root)
    payload = {
        "data_dir": str(root),
        "database": str(root / "job-copilot.sqlite3"),
        "schema_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
        "config": config,
    }
    conn.close()
    emit(payload, args.json)


def cmd_status(args):
    conn = connect(args.data_dir)
    tables = [
        "profiles", "campaigns", "postings", "resume_versions", "matches",
        "recommendations", "form_sessions", "applications", "interview_sessions",
    ]
    counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    active = get_active_campaign(conn)
    base = conn.execute("SELECT id FROM resume_versions WHERE active_base=1 LIMIT 1").fetchone()
    payload = {
        "data_dir": str(data_dir(args.data_dir)),
        "schema_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
        "active_campaign": row_dict(active),
        "active_base_resume": base[0] if base else None,
        "counts": counts,
    }
    conn.close()
    emit(payload, True)


def cmd_profile_show(args):
    conn = connect(args.data_dir)
    rows = conn.execute("SELECT * FROM profiles ORDER BY created_at").fetchall()
    payload = []
    for row in rows:
        item = row_dict(row)
        item["application_profile"] = redact_profile_for_output(json_loads(item.pop("application_profile_json"), {}))
        payload.append(item)
    conn.close()
    emit(payload, True)


def cmd_profile_update(args):
    requested_profile = None
    if args.profile_json:
        try:
            requested_profile = json.loads(args.profile_json)
        except json.JSONDecodeError as exc:
            fail(f"JSON 参数无效：{exc}")
        if not isinstance(requested_profile, dict):
            fail("profile-json 必须是 JSON 对象")
        validate_profile_json(requested_profile)
    conn = connect(args.data_dir)
    with transaction(conn):
        row = get_or_create_profile(conn, args.id, args.name_masked or "求职者")
        profile = requested_profile if requested_profile is not None else json_loads(row["application_profile_json"], {})
        if not isinstance(profile, dict):
            fail("profile-json 必须是 JSON 对象")
        validate_profile_json(profile)
        name_masked = args.name_masked or row["name_masked"]
        conn.execute(
            "UPDATE profiles SET name_masked=?, application_profile_json=?, updated_at=? WHERE id=?",
            (name_masked, json_dumps(profile), now_iso(), row["id"]),
        )
        out = row["id"]
    conn.close()
    emit({"profile_id": out, "updated": True}, args.json)


def cmd_fact_add(args):
    """Record one user-confirmed resume fact before it is reused."""
    if not args.claim or not args.detail or not args.stage:
        fail("新增 confirmed fact 需要 claim、detail 和 stage")
    conn = connect(args.data_dir)
    with transaction(conn):
        profile = get_or_create_profile(conn, args.profile_id, args.name_masked or "求职者")
        if args.source_resume_version_id:
            exists = conn.execute(
                "SELECT 1 FROM resume_versions WHERE id=? AND profile_id=?",
                (args.source_resume_version_id, profile["id"]),
            ).fetchone()
            if exists is None:
                fail(f"找不到属于该 Profile 的简历版本：{args.source_resume_version_id}")
        fact_id = args.id or uid("fact")
        conn.execute(
            """INSERT INTO confirmed_facts(
                 id,profile_id,claim,detail,stage,source_resume_version_id,confirmed_at
               ) VALUES(?,?,?,?,?,?,?)""",
            (fact_id, profile["id"], args.claim, args.detail, args.stage,
             args.source_resume_version_id, now_iso()),
        )
    conn.close()
    emit({"fact_id": fact_id, "profile_id": profile["id"], "recorded": True}, args.json)


def cmd_fact_list(args):
    conn = connect(args.data_dir)
    clauses = []
    values = []
    if args.profile_id:
        clauses.append("profile_id=?")
        values.append(args.profile_id)
    query = "SELECT * FROM confirmed_facts"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY confirmed_at"
    rows = conn.execute(query, values).fetchall()
    conn.close()
    emit(rows_dict(rows), True)


def cmd_campaign_create(args):
    require_route(args.route)
    quota = normalize_quota(args.daily_quota)
    score = normalize_score(args.min_match_score)
    conn = connect(args.data_dir)
    with transaction(conn):
        profile = get_or_create_profile(conn, args.profile_id, args.name_masked or "求职者")
        campaign_id = args.id or uid("campaign")
        stamp = now_iso()
        if args.activate:
            conn.execute("UPDATE campaigns SET active=0")
        conn.execute(
            """INSERT INTO campaigns(
              id,profile_id,name,route,active,directions_json,cities_json,
              priority_companies_json,excluded_companies_json,preferences_json,
              daily_quota,min_match_score,digest_time,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                campaign_id, profile["id"], args.name, args.route, int(args.activate),
                json_dumps(parse_csv(args.directions)), json_dumps(parse_csv(args.cities)),
                json_dumps(parse_csv(args.priority_companies)), json_dumps(parse_csv(args.excluded_companies)),
                json_dumps(parse_json_arg(args.preferences_json, {})), quota, score, args.digest_time,
                stamp, stamp,
            ),
        )
    conn.close()
    emit({"campaign_id": campaign_id, "active": bool(args.activate)}, args.json)


def cmd_campaign_list(args):
    conn = connect(args.data_dir)
    rows = conn.execute("SELECT * FROM campaigns ORDER BY created_at").fetchall()
    payload = []
    for row in rows:
        item = row_dict(row)
        for key in ("directions_json", "cities_json", "priority_companies_json", "excluded_companies_json", "preferences_json"):
            item[key[:-5] if key.endswith("_json") else key] = json_loads(item.pop(key), [] if key != "preferences_json" else {})
        payload.append(item)
    conn.close()
    emit(payload, True)


def cmd_campaign_activate(args):
    conn = connect(args.data_dir)
    with transaction(conn):
        if conn.execute("SELECT 1 FROM campaigns WHERE id=?", (args.id,)).fetchone() is None:
            fail(f"找不到 campaign：{args.id}")
        conn.execute("UPDATE campaigns SET active=0")
        conn.execute("UPDATE campaigns SET active=1, updated_at=? WHERE id=?", (now_iso(), args.id))
    conn.close()
    emit({"campaign_id": args.id, "active": True}, args.json)


def cmd_campaign_update(args):
    conn = connect(args.data_dir)
    row = conn.execute("SELECT * FROM campaigns WHERE id=?", (args.id,)).fetchone()
    if row is None:
        fail(f"找不到 campaign：{args.id}")
    fields = []
    values = []
    if args.name:
        fields.append("name=?"); values.append(args.name)
    if args.directions is not None:
        fields.append("directions_json=?"); values.append(json_dumps(parse_csv(args.directions)))
    if args.cities is not None:
        fields.append("cities_json=?"); values.append(json_dumps(parse_csv(args.cities)))
    if args.priority_companies is not None:
        fields.append("priority_companies_json=?"); values.append(json_dumps(parse_csv(args.priority_companies)))
    if args.excluded_companies is not None:
        fields.append("excluded_companies_json=?"); values.append(json_dumps(parse_csv(args.excluded_companies)))
    if args.daily_quota is not None:
        fields.append("daily_quota=?"); values.append(normalize_quota(args.daily_quota))
    if args.min_match_score is not None:
        fields.append("min_match_score=?"); values.append(normalize_score(args.min_match_score))
    if args.digest_time:
        fields.append("digest_time=?"); values.append(args.digest_time)
    if args.preferences_json is not None:
        value = parse_json_arg(args.preferences_json, {})
        if not isinstance(value, dict):
            fail("preferences-json 必须是 JSON 对象")
        fields.append("preferences_json=?"); values.append(json_dumps(value))
    if not fields:
        fail("至少提供一个要修改的字段")
    fields.append("updated_at=?"); values.append(now_iso()); values.append(args.id)
    with transaction(conn):
        conn.execute(f"UPDATE campaigns SET {', '.join(fields)} WHERE id=?", values)
    conn.close()
    emit({"campaign_id": args.id, "updated": True}, args.json)


def _posting_payload(raw, campaign_id):
    if not isinstance(raw, dict):
        raise ValueError("岗位条目必须是 JSON 对象")
    required = ("company", "title", "city", "route", "employment_type", "source_platform", "source_url", "source_tier", "jd_text")
    for key in required:
        if key not in raw:
            raise ValueError(f"岗位缺少 {key}")
    for key in ("company", "title", "city", "source_platform", "source_url", "source_tier"):
        if raw.get(key) in (None, ""):
            raise ValueError(f"岗位字段 {key} 不能为空")
    route = raw.get("route") or None
    if route not in VALID_ROUTES:
        raise ValueError("岗位 route 必须是 campus 或 social")
    city = raw.get("city") or "未注明"
    url = raw.get("official_url") or raw.get("source_url") or ""
    key = canonical_key(raw["company"], raw["title"], city, url, raw.get("official_job_id"))
    jd_text = raw.get("jd_text") or ""
    tier = raw.get("source_tier") or "C"
    if tier not in SOURCE_TIERS:
        raise ValueError("source_tier 必须是 A、B 或 C")
    return {
        "campaign_id": campaign_id,
        "canonical_key": key,
        "company": str(raw["company"]).strip(),
        "title": str(raw["title"]).strip(),
        "city": str(city).strip(),
        "route": route,
        "employment_type": raw.get("employment_type"),
        "official_url": raw.get("official_url") or None,
        "application_url": raw.get("application_url") or raw.get("official_url") or raw.get("source_url") or None,
        "jd_text": jd_text,
        "jd_hash": hash_text(jd_text) if jd_text else None,
        "deadline": raw.get("deadline") or None,
        "source_platform": raw.get("source_platform") or "未注明",
        "source_url": raw.get("source_url") or url,
        "source_tier": tier,
        "evidence": raw.get("evidence") or "",
        "official_job_id": raw.get("official_job_id") or None,
    }


def cmd_posting_import(args):
    source_path = Path(args.input)
    if not source_path.exists():
        fail(f"找不到输入文件：{source_path}")
    try:
        raw_items = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"无法读取岗位 JSON：{exc}")
    if not isinstance(raw_items, list):
        fail("岗位输入必须是 JSON 数组")
    validated = []
    for index, raw in enumerate(raw_items):
        try:
            validated.append(_posting_payload(raw, args.campaign))
        except ValueError as exc:
            fail(f"第 {index + 1} 条岗位无效：{exc}")
    conn = connect(args.data_dir)
    campaign = conn.execute("SELECT * FROM campaigns WHERE id=?", (args.campaign,)).fetchone()
    if campaign is None:
        conn.close()
        fail(f"找不到 campaign：{args.campaign}")
    for item in validated:
        if item["route"] != campaign["route"]:
            conn.close()
            fail(f"岗位 route={item['route']} 与 Campaign route={campaign['route']} 不一致")
    stamp = now_iso()
    created = updated = 0
    errors = []
    with transaction(conn):
        for item in validated:
            existing = conn.execute(
                "SELECT * FROM postings WHERE campaign_id=? AND canonical_key=?",
                (args.campaign, item["canonical_key"]),
            ).fetchone()
            if existing is None:
                compatible = conn.execute(
                    """SELECT p.* FROM postings p
                       WHERE p.campaign_id=? AND lower(trim(p.company))=?
                         AND lower(trim(p.title))=? AND lower(trim(p.city))=?
                         AND (p.official_url IS NOT NULL OR EXISTS
                              (SELECT 1 FROM posting_sources s WHERE s.posting_id=p.id AND s.tier IN ('A','B')))""",
                    (args.campaign, normalize_component(item["company"]), normalize_component(item["title"]), normalize_component(item["city"])),
                ).fetchall()
                if len(compatible) == 1:
                    existing = compatible[0]
                    if item.get("official_job_id") and existing["canonical_key"] != item["canonical_key"]:
                        conflict = conn.execute("SELECT 1 FROM postings WHERE campaign_id=? AND canonical_key=? AND id<>?", (args.campaign, item["canonical_key"], existing["id"])).fetchone()
                        if conflict is None:
                            conn.execute("UPDATE postings SET canonical_key=? WHERE id=?", (item["canonical_key"], existing["id"]))
            if existing:
                conn.execute(
                    """UPDATE postings SET company=?,title=?,city=?,route=?,employment_type=?,
                       official_url=COALESCE(?,official_url),application_url=COALESCE(?,application_url),
                       jd_text=COALESCE(?,jd_text),jd_hash=COALESCE(?,jd_hash),deadline=COALESCE(?,deadline),
                       last_verified_at=? WHERE id=?""",
                    (item["company"], item["title"], item["city"], item["route"], item["employment_type"],
                     item["official_url"], item["application_url"], item["jd_text"] or None, item["jd_hash"],
                     item["deadline"], stamp, existing["id"]),
                )
                posting_id = existing["id"]; updated += 1
            else:
                posting_id = uid("posting")
                conn.execute(
                    """INSERT INTO postings(
                      id,campaign_id,canonical_key,company,title,city,route,employment_type,
                      official_url,application_url,jd_text,jd_hash,deadline,status,first_seen_at,last_verified_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (posting_id, args.campaign, item["canonical_key"], item["company"], item["title"], item["city"],
                     item["route"], item["employment_type"], item["official_url"], item["application_url"],
                     item["jd_text"] or None, item["jd_hash"], item["deadline"], "active", stamp, stamp),
                )
                created += 1
            source_exists = conn.execute(
                "SELECT 1 FROM posting_sources WHERE posting_id=? AND url=?",
                (posting_id, item["source_url"]),
            ).fetchone()
            if not source_exists and item["source_url"]:
                conn.execute(
                    """INSERT INTO posting_sources(id,posting_id,tier,platform,url,evidence,discovered_at,verified_at)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (uid("source"), posting_id, item["source_tier"], item["source_platform"], item["source_url"],
                     item["evidence"], stamp, stamp if item["source_tier"] in {"A", "B"} else None),
                )
    conn.close()
    emit({"created": created, "updated": updated, "errors": errors}, args.json)


def cmd_posting_list(args):
    conn = connect(args.data_dir)
    clauses = ["p.campaign_id=?"]
    values = [args.campaign]
    if args.status:
        clauses.append("p.status=?"); values.append(args.status)
    if args.route:
        clauses.append("p.route=?"); values.append(args.route)
    rows = conn.execute(
        """SELECT p.*, COALESCE(MIN(s.tier),'C') AS source_tier
           FROM postings p LEFT JOIN posting_sources s ON s.posting_id=p.id
           WHERE """ + " AND ".join(clauses) + " GROUP BY p.id ORDER BY p.first_seen_at DESC", values).fetchall()
    conn.close()
    emit(rows_dict(rows), True)


def cmd_posting_archive(args):
    conn = connect(args.data_dir)
    with transaction(conn):
        row = conn.execute("SELECT id FROM postings WHERE id=?", (args.id,)).fetchone()
        if row is None:
            fail(f"找不到岗位：{args.id}")
        stamp = now_iso()
        conn.execute("UPDATE postings SET status='archived',archived_at=? WHERE id=?", (stamp, args.id))
        conn.execute("UPDATE recommendations SET status='archived',archived_reason=? WHERE posting_id=? AND status NOT IN ('applied','archived')", (args.reason or "用户归档", args.id))
    conn.close()
    emit({"posting_id": args.id, "archived": True}, args.json)


def cmd_posting_verify(args):
    conn = connect(args.data_dir)
    row = conn.execute("SELECT id FROM postings WHERE id=?", (args.id,)).fetchone()
    if row is None:
        fail(f"找不到岗位：{args.id}")
    if args.tier not in SOURCE_TIERS:
        fail("tier 必须是 A、B 或 C")
    with transaction(conn):
        conn.execute("UPDATE postings SET official_url=COALESCE(?,official_url),application_url=COALESCE(?,application_url),last_verified_at=?,status='active' WHERE id=?", (args.official_url, args.application_url, now_iso(), args.id))
        conn.execute("UPDATE posting_sources SET verified_at=? WHERE posting_id=? AND tier=?", (now_iso(), args.id, args.tier))
        if conn.execute("SELECT 1 FROM posting_sources WHERE posting_id=? AND tier=?", (args.id, args.tier)).fetchone() is None:
            conn.execute("INSERT INTO posting_sources(id,posting_id,tier,platform,url,evidence,discovered_at,verified_at) VALUES(?,?,?,?,?,?,?,?)", (uid("source"), args.id, args.tier, args.platform or "官方核实", args.official_url or args.application_url or "", args.evidence or "", now_iso(), now_iso()))
    conn.close()
    emit({"posting_id": args.id, "tier": args.tier, "verified": True}, args.json)


def _validate_evaluation(item):
    required = ("posting_id", "resume_version_id", "eligible", "coverage", "confidence", "jd_hash")
    for key in required:
        if key not in item:
            raise ValueError(f"匹配结果缺少 {key}")
    if not isinstance(item["posting_id"], str) or not item["posting_id"]:
        raise ValueError("posting_id 必须是非空字符串")
    if not isinstance(item["resume_version_id"], str) or not item["resume_version_id"]:
        raise ValueError("resume_version_id 必须是非空字符串")
    if not isinstance(item["eligible"], bool):
        raise ValueError("eligible 必须是布尔值")
    if not isinstance(item["jd_hash"], str) or not item["jd_hash"]:
        raise ValueError("jd_hash 必须是非空字符串")
    if item["confidence"] not in {"high", "medium", "low"}:
        raise ValueError("confidence 必须是 high、medium 或 low")
    if not isinstance(item["coverage"], int) or isinstance(item["coverage"], bool):
        raise ValueError("coverage 必须是整数")
    coverage = int(item["coverage"])
    if not 0 <= coverage <= 100:
        raise ValueError("coverage 必须在 0 到 100 之间")
    expected_confidence = "high" if coverage >= 80 else "medium" if coverage >= 60 else "low"
    if item["confidence"] != expected_confidence:
        raise ValueError("confidence 与 coverage 不一致")
    score = item.get("score")
    if item.get("eligible"):
        if not isinstance(score, int) or isinstance(score, bool) or not 0 <= int(score) <= 100:
            raise ValueError("eligible=true 时 score 必须是 0 到 100")
    elif score is not None:
        raise ValueError("eligible=false 时 score 必须为 null")
    for key in ("hard_failures", "evidence", "gaps", "actions"):
        if key in item and not isinstance(item[key], list):
            raise ValueError(f"{key} 必须是数组")
    if "dimensions" in item and not isinstance(item["dimensions"], dict):
        raise ValueError("dimensions 必须是对象")


def _best_source_tier(conn, posting_id):
    tiers = [r[0] for r in conn.execute("SELECT tier FROM posting_sources WHERE posting_id=?", (posting_id,)).fetchall()]
    return min(tiers) if tiers else "C"


def _is_expired(deadline):
    if not deadline:
        return False
    try:
        return datetime.fromisoformat(str(deadline)[:10]).date() < datetime.now(APP_TIMEZONE).date()
    except ValueError:
        return False


def _ensure_recommendation(conn, item, posting, match_id, resume_version_id, root=None):
    # Keep one live recommendation card per posting.  Tailoring a resume should
    # replace the card's resume reference, not create a duplicate card for the
    # same job.
    existing = conn.execute(
        """SELECT id,status FROM recommendations
           WHERE posting_id=? AND status NOT IN ('archived','expired')
           ORDER BY recommended_at DESC LIMIT 1""",
        (posting["id"],),
    ).fetchone()
    if not item.get("eligible") or item.get("score") is None:
        if existing and existing["status"] != "applied":
            conn.execute("UPDATE recommendations SET status='archived',archived_reason=? WHERE id=?", ("重新评分后不再符合推荐条件", existing["id"]))
        return None
    if conn.execute("SELECT 1 FROM applications WHERE posting_id=? LIMIT 1", (posting["id"],)).fetchone():
        return None
    campaign = conn.execute("SELECT min_match_score FROM campaigns WHERE id=?", (posting["campaign_id"],)).fetchone()
    score_ok = int(item["score"]) >= int(campaign[0])
    source_ok = _best_source_tier(conn, posting["id"]) in {"A", "B"}
    coverage_ok = int(item["coverage"]) >= 60
    if not (score_ok and source_ok and coverage_ok and posting["status"] == "active" and not _is_expired(posting["deadline"])):
        if existing and existing["status"] != "applied":
            conn.execute("UPDATE recommendations SET status='archived',archived_reason=? WHERE id=?", ("重新评分后不再符合推荐条件", existing["id"]))
        return None
    if existing:
        conn.execute("UPDATE recommendations SET match_id=?,resume_version_id=?,last_progress_at=COALESCE(last_progress_at,?) WHERE id=?", (match_id, resume_version_id, now_iso(), existing["id"]))
        return existing["id"]
    stamp = now_iso()
    config = load_config(data_dir(root))
    due = hours_from(stamp, float(config.get("decision_after_hours", 24)))
    rec_id = uid("rec")
    conn.execute(
        """INSERT INTO recommendations(id,campaign_id,posting_id,match_id,resume_version_id,status,recommended_at,decision_due_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (rec_id, posting["campaign_id"], posting["id"], match_id, resume_version_id, "pending", stamp, due),
    )
    return rec_id


def _reset_recommendation_progress(conn, posting_id, stamp, root=None):
    """A meaningful preparation action starts a fresh 24-hour decision clock."""
    config = load_config(data_dir(root))
    due = hours_from(stamp, float(config.get("decision_after_hours", 24)))
    conn.execute(
        """UPDATE recommendations SET status='preparing',last_progress_at=?,decision_due_at=?
           WHERE posting_id=? AND status IN ('pending','snoozed','preparing')""",
        (stamp, due, posting_id),
    )


def cmd_match_record(args):
    path = Path(args.input)
    if not path.exists():
        fail(f"找不到匹配结果：{path}")
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"无法读取匹配结果：{exc}")
    if not isinstance(items, list):
        fail("匹配结果必须是 JSON 数组")
    conn = connect(args.data_dir)
    saved = recommendations = 0
    errors = []
    with transaction(conn):
        for item in items:
            try:
                _validate_evaluation(item)
            except (TypeError, ValueError) as exc:
                errors.append(str(exc)); continue
            posting = conn.execute("SELECT * FROM postings WHERE id=?", (item["posting_id"],)).fetchone()
            resume = conn.execute("SELECT id FROM resume_versions WHERE id=?", (item["resume_version_id"],)).fetchone()
            if posting is None or resume is None:
                errors.append(f"找不到岗位或简历版本：{item.get('posting_id')}"); continue
            if not posting["jd_hash"] or item["jd_hash"] != posting["jd_hash"]:
                errors.append(f"岗位 JD 哈希不匹配：{item.get('posting_id')}"); continue
            existing = conn.execute("SELECT id FROM matches WHERE posting_id=? AND resume_version_id=? AND jd_hash=?", (item["posting_id"], item["resume_version_id"], item["jd_hash"])).fetchone()
            match_id = existing[0] if existing else uid("match")
            params = (
                match_id, item["posting_id"], item["resume_version_id"], int(bool(item["eligible"])),
                int(item["score"]) if item.get("score") is not None else None, int(item["coverage"]), item["confidence"],
                json_dumps(item.get("hard_failures", [])), json_dumps(item.get("dimensions", {})),
                json_dumps(item.get("evidence", [])), json_dumps(item.get("gaps", [])), json_dumps(item.get("actions", [])),
                item["jd_hash"], item.get("evaluated_at") or now_iso(),
            )
            if existing:
                conn.execute("""UPDATE matches SET eligible=?,score=?,coverage=?,confidence=?,hard_failures_json=?,dimensions_json=?,evidence_json=?,gaps_json=?,actions_json=?,evaluated_at=? WHERE id=?""", params[3:12] + (params[13], params[0]))
            else:
                conn.execute("""INSERT INTO matches(id,posting_id,resume_version_id,eligible,score,coverage,confidence,hard_failures_json,dimensions_json,evidence_json,gaps_json,actions_json,jd_hash,evaluated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", params)
            saved += 1
            rec_id = _ensure_recommendation(conn, item, posting, match_id, item["resume_version_id"], args.data_dir)
            if rec_id:
                recommendations += 1
    conn.close()
    emit({"saved": saved, "recommendations_created_or_existing": recommendations, "errors": errors}, args.json)


def cmd_match_pending(args):
    conn = connect(args.data_dir)
    campaign = (
        conn.execute("SELECT * FROM campaigns WHERE id=?", (args.campaign,)).fetchone()
        if args.campaign
        else conn.execute("SELECT * FROM campaigns WHERE active=1 LIMIT 1").fetchone()
    )
    if campaign is None:
        fail("没有 active Campaign；请先完成初始化")
    resume_id = args.resume_version_id
    if not resume_id:
        row = conn.execute("SELECT id FROM resume_versions WHERE profile_id=? AND active_base=1", (campaign["profile_id"],)).fetchone()
        resume_id = row[0] if row else None
    if not resume_id:
        fail("没有 active base 简历；请先导入简历")
    rows = conn.execute(
        """SELECT p.*,COALESCE(MIN(s.tier),'C') AS source_tier
           FROM postings p LEFT JOIN posting_sources s ON s.posting_id=p.id
           WHERE p.campaign_id=? AND p.status='active'
             AND NOT EXISTS (SELECT 1 FROM matches m WHERE m.posting_id=p.id AND m.resume_version_id=? AND m.jd_hash=p.jd_hash)
           GROUP BY p.id ORDER BY p.first_seen_at DESC""",
        (campaign["id"], resume_id),
    ).fetchall()
    conn.close()
    emit({"campaign_id": campaign["id"], "resume_version_id": resume_id, "postings": rows_dict(rows)}, True)


def cmd_match_list(args):
    conn = connect(args.data_dir)
    clauses = []
    values = []
    if args.posting_id:
        clauses.append("m.posting_id=?"); values.append(args.posting_id)
    if args.resume_version_id:
        clauses.append("m.resume_version_id=?"); values.append(args.resume_version_id)
    query = "SELECT m.*,p.company,p.title,p.city FROM matches m JOIN postings p ON p.id=m.posting_id"
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY m.evaluated_at DESC"
    rows = conn.execute(query, values).fetchall()
    payload = []
    for row in rows:
        item = row_dict(row)
        for key in ("hard_failures_json", "dimensions_json", "evidence_json", "gaps_json", "actions_json"):
            item[key[:-5]] = json_loads(item.pop(key), [] if key != "dimensions_json" else {})
        payload.append(item)
    conn.close()
    emit(payload, True)


def _safe_copy(src: Path, dest_dir: Path, label: str) -> Path:
    if not src.exists() or not src.is_file():
        fail(f"文件不存在：{src}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{label}{src.suffix.lower()}"
    suffix = 2
    while target.exists():
        target = dest_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{label}-{suffix}{src.suffix.lower()}"
        suffix += 1
    shutil.copy2(src, target)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return target


def cmd_resume_import(args):
    src = Path(args.file)
    if not src.exists():
        fail(f"找不到简历文件：{src}")
    conn = connect(args.data_dir)
    with transaction(conn):
        profile = get_or_create_profile(conn, args.profile_id, args.name_masked or "求职者")
        version_id = args.id or datetime.now().strftime("%Y%m%d-base")
        version_dir = data_dir(args.data_dir) / "resumes" / "versions" / version_id
        version_dir.mkdir(parents=True, exist_ok=True)
        original = _safe_copy(src, data_dir(args.data_dir) / "originals", version_id)
        text_path = version_dir / "resume.txt"
        try:
            from extract_resume import extract_file
        except ImportError:
            from .extract_resume import extract_file
        text = extract_file(src)
        text_path.write_text(text, encoding="utf-8")
        try:
            text_path.chmod(0o600)
        except OSError:
            pass
        photo_path = None
        photo_source = None
        if args.photo:
            photo_path = _safe_copy(Path(args.photo), data_dir(args.data_dir) / "photos", version_id)
            photo_source = str(Path(args.photo).expanduser().resolve())
        elif src.suffix.lower() == ".pdf":
            try:
                from extract_resume import photo_from_pdf
            except ImportError:
                from .extract_resume import photo_from_pdf
            try:
                photo_bytes = photo_from_pdf(src)
            except RuntimeError:
                photo_bytes = None
            if photo_bytes:
                photo_path = data_dir(args.data_dir) / "photos" / f"{version_id}.png"
                photo_path.write_bytes(photo_bytes)
                try:
                    photo_path.chmod(0o600)
                except OSError:
                    pass
                photo_source = str(src.resolve())
        if args.set_base:
            conn.execute("UPDATE resume_versions SET active_base=0 WHERE profile_id=?", (profile["id"],))
        stamp = now_iso()
        conn.execute(
            """INSERT OR REPLACE INTO resume_versions(
              id,profile_id,kind,label,original_path,text_path,photo_path,hashes_json,tags_json,
              honesty_checked,active_base,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (version_id, profile["id"], args.kind, args.label or "导入简历", str(original.relative_to(data_dir(args.data_dir))),
             str(text_path.relative_to(data_dir(args.data_dir))), str(photo_path.relative_to(data_dir(args.data_dir))) if photo_path else None,
             json_dumps({"original": hash_file(original), "text": hash_file(text_path)}), json_dumps(parse_csv(args.tags)),
             int(args.honesty_checked), int(args.set_base), stamp),
        )
        conn.execute("UPDATE profiles SET generated_from_resume_id=?,updated_at=? WHERE id=?", (version_id, stamp, profile["id"]))
    conn.close()
    emit({"resume_version_id": version_id, "text_length": len(text), "original_path": str(original),
          "photo_path": str(photo_path) if photo_path else None, "photo_source": photo_source}, args.json)


def cmd_resume_register(args):
    conn = connect(args.data_dir)
    with transaction(conn):
        profile = get_or_create_profile(conn, args.profile_id, args.name_masked or "求职者")
        if args.kind not in {"base", "tailored"}:
            fail("kind 必须是 base 或 tailored")
        if args.active_base:
            conn.execute("UPDATE resume_versions SET active_base=0 WHERE profile_id=?", (profile["id"],))
        conn.execute(
            """INSERT OR REPLACE INTO resume_versions(
              id,profile_id,kind,base_version_id,target_posting_id,label,original_path,text_path,html_path,pdf_path,photo_path,
              hashes_json,tags_json,score_before,score_after,honesty_checked,active_base,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (args.id, profile["id"], args.kind, args.base_version_id, args.target_posting_id, args.label,
             args.original_path, args.text_path, args.html_path, args.pdf_path, args.photo_path,
             json_dumps(parse_json_arg(args.hashes_json, {})), json_dumps(parse_csv(args.tags)),
             args.score_before, args.score_after, int(args.honesty_checked), int(args.active_base), args.created_at or now_iso()),
        )
        if args.target_posting_id:
            _reset_recommendation_progress(conn, args.target_posting_id, now_iso(), args.data_dir)
    conn.close()
    emit({"resume_version_id": args.id, "registered": True}, args.json)


def cmd_resume_list(args):
    conn = connect(args.data_dir)
    rows = conn.execute("SELECT * FROM resume_versions ORDER BY created_at DESC").fetchall()
    conn.close()
    emit(rows_dict(rows), True)


def cmd_resume_set_base(args):
    conn = connect(args.data_dir)
    with transaction(conn):
        row = conn.execute("SELECT profile_id FROM resume_versions WHERE id=?", (args.id,)).fetchone()
        if row is None:
            fail(f"找不到简历版本：{args.id}")
        conn.execute("UPDATE resume_versions SET active_base=0 WHERE profile_id=?", (row[0],))
        conn.execute("UPDATE resume_versions SET active_base=1 WHERE id=?", (args.id,))
    conn.close()
    emit({"resume_version_id": args.id, "active_base": True}, args.json)


def cmd_form_start(args):
    conn = connect(args.data_dir)
    for table, value in (("postings", args.posting_id), ("resume_versions", args.resume_version_id)):
        if conn.execute(f"SELECT 1 FROM {table} WHERE id=?", (value,)).fetchone() is None:
            fail(f"找不到 {table} 记录：{value}")
    session_id = args.id or uid("form")
    stamp = now_iso()
    with transaction(conn):
        conn.execute("INSERT INTO form_sessions(id,posting_id,resume_version_id,form_url,status,started_at) VALUES(?,?,?,?,?,?)", (session_id, args.posting_id, args.resume_version_id, args.form_url, "started", stamp))
        _reset_recommendation_progress(conn, args.posting_id, stamp, args.data_dir)
    conn.close()
    emit({"form_session_id": session_id, "status": "started"}, args.json)


def cmd_form_update(args):
    if args.status not in {"blocked", "draft_filled", "ready_for_review", "submission_confirmed", "abandoned"}:
        fail("非法表单状态")
    conn = connect(args.data_dir)
    if conn.execute("SELECT 1 FROM form_sessions WHERE id=?", (args.id,)).fetchone() is None:
        fail(f"找不到表单会话：{args.id}")
    blocked = parse_json_arg(args.blocked_fields_json, [])
    manifest = parse_json_arg(args.manifest_json, {})
    if not isinstance(blocked, list):
        fail("blocked-fields-json 必须是数组")
    if not isinstance(manifest, dict):
        fail("manifest-json 必须是对象")
    blocked = redact_structure(blocked)
    manifest = redact_structure(manifest)
    with transaction(conn):
        stamp = now_iso()
        conn.execute("UPDATE form_sessions SET status=?,redacted_manifest_json=?,blocked_fields_json=?,filled_at=COALESCE(filled_at,?),confirmation_observed_at=? WHERE id=?", (args.status, json_dumps(manifest), json_dumps(blocked), stamp if args.status in {"draft_filled", "ready_for_review", "submission_confirmed"} else None, stamp if args.status == "submission_confirmed" else None, args.id))
        if args.status in {"draft_filled", "ready_for_review"}:
            row = conn.execute("SELECT posting_id FROM form_sessions WHERE id=?", (args.id,)).fetchone()
            _reset_recommendation_progress(conn, row[0], stamp, args.data_dir)
    conn.close()
    emit({"form_session_id": args.id, "status": args.status}, args.json)


def cmd_form_blocked(args):
    args.status = "blocked"
    cmd_form_update(args)


def cmd_form_ready(args):
    args.status = "ready_for_review"
    cmd_form_update(args)


def cmd_application_mark_submitted(args):
    conn = connect(args.data_dir)
    posting = conn.execute(
        """SELECT p.*,c.profile_id
           FROM postings p JOIN campaigns c ON c.id=p.campaign_id
           WHERE p.id=?""",
        (args.posting_id,),
    ).fetchone()
    resume = conn.execute(
        "SELECT id,profile_id FROM resume_versions WHERE id=?",
        (args.resume_version_id,),
    ).fetchone()
    if posting is None or resume is None:
        fail("posting 或 resume_version 不存在")
    if posting["profile_id"] != resume["profile_id"]:
        fail("posting 与 resume_version 不属于同一 Profile", 3)
    if args.form_session_id:
        form = conn.execute(
            """SELECT posting_id,resume_version_id FROM form_sessions WHERE id=?""",
            (args.form_session_id,),
        ).fetchone()
        if form is None:
            fail(f"找不到表单会话：{args.form_session_id}")
        if (
            form["posting_id"] != args.posting_id
            or form["resume_version_id"] != args.resume_version_id
        ):
            fail("form session 与 posting/resume 不一致", 3)
    if conn.execute("SELECT id FROM applications WHERE posting_id=? AND resume_version_id=?", (args.posting_id, args.resume_version_id)).fetchone():
        fail("同一岗位和简历版本已经记录过投递", 3)
    application_id = args.id or uid("application")
    stamp = normalize_iso(args.applied_at or now_iso(), "applied-at")
    next_action_at = (
        normalize_iso(args.next_action_at, "next-action-at")
        if args.next_action_at
        else _followup_for_posting(conn, args.posting_id, stamp, args.data_dir)
    )
    with transaction(conn):
        conn.execute("INSERT INTO applications(id,posting_id,resume_version_id,form_session_id,channel,applied_at,current_stage,next_action_at,last_update_at) VALUES(?,?,?,?,?,?,?,?,?)", (application_id, args.posting_id, args.resume_version_id, args.form_session_id, args.channel, stamp, "已投递", next_action_at, stamp))
        conn.execute("INSERT INTO application_events(id,application_id,event_type,stage,note,occurred_at) VALUES(?,?,?,?,?,?)", (uid("event"), application_id, "submitted", "已投递", redact(args.note or "用户确认已提交"), stamp))
        conn.execute(
            "INSERT INTO application_events(id,application_id,event_type,stage,note,occurred_at) VALUES(?,?,?,?,?,?)",
            (uid("event"), application_id, "followup_scheduled", "已投递", f"下次状态检查：{next_action_at}", stamp),
        )
        conn.execute("UPDATE recommendations SET status='applied',last_progress_at=? WHERE posting_id=? AND status NOT IN ('archived','expired')", (stamp, args.posting_id))
        if args.form_session_id:
            conn.execute("UPDATE form_sessions SET status='submission_confirmed',confirmation_observed_at=? WHERE id=?", (stamp, args.form_session_id))
    conn.close()
    emit({"application_id": application_id, "stage": "已投递", "next_action_at": next_action_at}, args.json)


def _find_applications(conn, identifier):
    rows = conn.execute(
        """SELECT a.*,p.company,p.title,p.city,p.campaign_id,p.jd_text,p.application_url,
                  c.profile_id,c.route,c.digest_time
           FROM applications a
           JOIN postings p ON p.id=a.posting_id
           JOIN campaigns c ON c.id=p.campaign_id
           WHERE a.id=? OR p.company LIKE ? OR p.title LIKE ?
           ORDER BY a.applied_at DESC""",
        (identifier, f"%{identifier}%", f"%{identifier}%"),
    ).fetchall()
    return rows


def _application_candidates(rows):
    fields = (
        "id", "company", "title", "city", "current_stage", "applied_at",
        "resume_version_id",
    )
    return [{field: row[field] for field in fields} for row in rows]


def cmd_application_stage(args):
    if args.stage not in VALID_STAGES:
        fail("非法投递阶段")
    conn = connect(args.data_dir)
    rows = _find_applications(conn, args.id)
    if not rows:
        fail(f"找不到投递记录：{args.id}")
    if len(rows) > 1:
        emit({"ambiguous": True, "candidates": _application_candidates(rows)}, True)
        conn.close()
        return
    app = rows[0]
    stamp = normalize_iso(args.date or now_iso(), "date")
    closed = int(args.stage in TERMINAL_STAGES)
    next_action_at = None if closed else (
        normalize_iso(args.next_action_at, "next-action-at") if args.next_action_at else None
    )
    with transaction(conn):
        conn.execute("UPDATE applications SET current_stage=?,closed=?,outcome=?,next_action_at=?,last_update_at=? WHERE id=?", (args.stage, closed, args.stage if closed else None, next_action_at, stamp, app["id"]))
        conn.execute("INSERT INTO application_events(id,application_id,event_type,stage,note,occurred_at) VALUES(?,?,?,?,?,?)", (uid("event"), app["id"], "stage_update", args.stage, redact(args.note or ""), stamp))
    conn.close()
    emit({"application_id": app["id"], "company": app["company"], "title": app["title"], "stage": args.stage, "next_action_at": next_action_at}, args.json)


def cmd_application_check_status(args):
    if args.result == "updated":
        if not args.stage:
            fail("result=updated 时必须提供 --stage")
        if args.stage not in VALID_STAGES:
            fail("非法投递阶段")
    elif args.stage:
        fail("只有 result=updated 时可以提供 --stage")

    conn = connect(args.data_dir)
    rows = _find_applications(conn, args.id)
    if not rows:
        fail(f"找不到投递记录：{args.id}")
    if len(rows) > 1:
        emit({"ambiguous": True, "candidates": _application_candidates(rows)}, True)
        conn.close()
        return

    app = rows[0]
    if app["closed"] and args.result == "no-update":
        conn.close()
        fail("终止态投递不能顺延状态提醒", 3)
    stamp = normalize_iso(args.date or now_iso(), "date")
    if args.result == "no-update":
        next_action_at = (
            normalize_iso(args.next_action_at, "next-action-at")
            if args.next_action_at
            else _followup_for_posting(conn, app["posting_id"], stamp, args.data_dir)
        )
        stage = app["current_stage"]
        closed = app["closed"]
        outcome = app["outcome"]
        event_type = "status_checked_no_update"
        note = args.note or "用户已查看，暂无更新"
    elif args.result == "updated":
        stage = args.stage
        closed = int(stage in TERMINAL_STAGES)
        outcome = stage if closed else None
        next_action_at = None if closed else (
            normalize_iso(args.next_action_at, "next-action-at")
            if args.next_action_at
            else _followup_for_posting(conn, app["posting_id"], stamp, args.data_dir)
        )
        event_type = "stage_update"
        note = args.note or "用户查看后报告状态更新"
    else:
        stage = app["current_stage"]
        closed = app["closed"]
        outcome = app["outcome"]
        next_action_at = None
        event_type = "followup_stopped"
        note = args.note or "用户停止状态提醒"

    with transaction(conn):
        conn.execute(
            """UPDATE applications
               SET current_stage=?,closed=?,outcome=?,next_action_at=?,last_update_at=?
               WHERE id=?""",
            (stage, closed, outcome, next_action_at, stamp, app["id"]),
        )
        conn.execute(
            """INSERT INTO application_events(
                 id,application_id,event_type,stage,note,occurred_at
               ) VALUES(?,?,?,?,?,?)""",
            (uid("event"), app["id"], event_type, stage, redact(note), stamp),
        )
    conn.close()
    emit(
        {
            "application_id": app["id"],
            "company": app["company"],
            "title": app["title"],
            "result": args.result,
            "stage": stage,
            "closed": bool(closed),
            "next_action_at": next_action_at,
        },
        args.json,
    )


def cmd_application_list(args):
    conn = connect(args.data_dir)
    query = "SELECT a.*,p.company,p.title,p.city FROM applications a JOIN postings p ON p.id=a.posting_id"
    if args.open_only:
        query += " WHERE a.closed=0"
    query += " ORDER BY a.applied_at DESC"
    rows = conn.execute(query).fetchall()
    conn.close()
    emit(rows_dict(rows), True)


def cmd_application_stats(args):
    conn = connect(args.data_dir)
    total = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    passed = conn.execute("SELECT COUNT(*) FROM applications WHERE current_stage IN ('筛选中','在线测评','笔试','HR沟通','一面','二面','终面','Offer')").fetchone()[0]
    interviews = conn.execute("SELECT COUNT(*) FROM applications WHERE current_stage IN ('一面','二面','终面','Offer')").fetchone()[0]
    offers = conn.execute("SELECT COUNT(*) FROM applications WHERE current_stage='Offer'").fetchone()[0]
    by_version = rows_dict(conn.execute("SELECT resume_version_id,COUNT(*) AS applied,SUM(CASE WHEN current_stage IN ('筛选中','在线测评','笔试','HR沟通','一面','二面','终面','Offer') THEN 1 ELSE 0 END) AS passed FROM applications GROUP BY resume_version_id ORDER BY applied DESC").fetchall())
    by_direction = rows_dict(conn.execute("""SELECT p.title AS direction,COUNT(*) AS applied,
        SUM(CASE WHEN a.current_stage IN ('筛选中','在线测评','笔试','HR沟通','一面','二面','终面','Offer') THEN 1 ELSE 0 END) AS passed
        FROM applications a JOIN postings p ON p.id=a.posting_id GROUP BY p.title ORDER BY applied DESC""").fetchall())
    by_source = rows_dict(conn.execute("""SELECT a.channel AS source,COUNT(*) AS applied,
        SUM(CASE WHEN a.current_stage IN ('筛选中','在线测评','笔试','HR沟通','一面','二面','终面','Offer') THEN 1 ELSE 0 END) AS passed
        FROM applications a GROUP BY a.channel ORDER BY applied DESC""").fetchall())
    conn.close()
    payload = {"total": total, "passed": passed, "interviews": interviews, "offers": offers,
               "by_direction": by_direction, "by_resume_version": by_version, "by_source": by_source,
               "sample_warning": total < 10, "sample_warning_text": "样本过少，不宜判断某版简历更优" if total < 10 else None}
    emit(payload, True)


def _interview_output(row, include_details=True):
    item = row_dict(row)
    if not item:
        return None
    for field, default in (
        ("plan_json", {}),
        ("progress_json", {}),
        ("summary_json", {}),
    ):
        parsed = json_loads(item.pop(field), default)
        if include_details:
            item[field[:-5]] = parsed
    return item


def cmd_interview_start(args):
    question_count = int(args.question_count)
    if not 1 <= question_count <= 20:
        fail("question-count 必须在 1 到 20 之间")
    if args.mode not in INTERVIEW_MODES:
        fail("非法模拟面试模式")
    provided_plan = None
    if args.plan_json:
        provided_plan = parse_json_arg(args.plan_json, {})
        if not isinstance(provided_plan, dict):
            fail("plan-json 必须是 JSON 对象")
        _validate_interview_payload(provided_plan, "plan-json")
        provided_plan = redact_structure(provided_plan)

    conn = connect(args.data_dir)
    with transaction(conn):
        application = None
        posting = None
        campaign = None
        resume_version_id = args.resume_version_id

        if args.application_id:
            application = conn.execute(
                """SELECT a.*,p.company,p.title,p.jd_text,p.campaign_id,
                          c.profile_id,c.route
                   FROM applications a
                   JOIN postings p ON p.id=a.posting_id
                   JOIN campaigns c ON c.id=p.campaign_id
                   WHERE a.id=?""",
                (args.application_id,),
            ).fetchone()
            if application is None:
                fail(f"找不到投递记录：{args.application_id}")
            profile_id = application["profile_id"]
            posting_id = application["posting_id"]
            resume_version_id = application["resume_version_id"]
            company = application["company"]
            title = application["title"]
            route = application["route"]
            has_jd = bool((application["jd_text"] or "").strip())
            if args.profile_id and args.profile_id != profile_id:
                fail("application 与 profile 不属于同一用户", 3)
            if args.posting_id and args.posting_id != posting_id:
                fail("application 与 posting 不一致", 3)
            if args.resume_version_id and args.resume_version_id != resume_version_id:
                fail("application 与 resume version 不一致", 3)
            if args.company and normalize_component(args.company) != normalize_component(company):
                fail("application 与 company 不一致", 3)
            if args.title and normalize_component(args.title) != normalize_component(title):
                fail("application 与 title 不一致", 3)
        elif args.posting_id:
            posting = conn.execute(
                """SELECT p.*,c.profile_id,c.route
                   FROM postings p JOIN campaigns c ON c.id=p.campaign_id
                   WHERE p.id=?""",
                (args.posting_id,),
            ).fetchone()
            if posting is None:
                fail(f"找不到岗位：{args.posting_id}")
            profile_id = posting["profile_id"]
            posting_id = posting["id"]
            company = posting["company"]
            title = posting["title"]
            route = posting["route"]
            has_jd = bool((posting["jd_text"] or "").strip())
            if args.profile_id and args.profile_id != profile_id:
                fail("posting 与 profile 不属于同一用户", 3)
        else:
            profile = get_or_create_profile(conn, args.profile_id, "求职者")
            profile_id = profile["id"]
            if not args.company or not args.title:
                fail("独立模拟面试必须提供 --company 和 --title")
            company = args.company.strip()
            title = args.title.strip()
            posting_id = None
            has_jd = False
            campaign = conn.execute(
                "SELECT route FROM campaigns WHERE profile_id=? AND active=1 LIMIT 1",
                (profile_id,),
            ).fetchone()
            route = args.route or (campaign["route"] if campaign else None)
            if route not in VALID_ROUTES:
                fail("没有可推断的求职路径，请提供 --route campus 或 social")

        if resume_version_id:
            resume = conn.execute(
                "SELECT id FROM resume_versions WHERE id=? AND profile_id=?",
                (resume_version_id, profile_id),
            ).fetchone()
            if resume is None:
                fail("resume version 不存在或不属于当前 Profile")
        elif not application:
            resume = conn.execute(
                "SELECT id FROM resume_versions WHERE profile_id=? AND active_base=1 LIMIT 1",
                (profile_id,),
            ).fetchone()
            resume_version_id = resume["id"] if resume else None

        round_label = (args.round_label or "未注明").strip()
        focus = (args.focus or "综合").strip()
        if provided_plan is not None:
            plan = provided_plan
        else:
            plan = _default_interview_plan(
                route, round_label, focus, question_count, has_jd
            )

        stamp = normalize_iso(args.started_at or now_iso(), "started-at")
        session_id = args.id or uid("interview")
        conn.execute(
            """INSERT INTO interview_sessions(
                 id,profile_id,application_id,posting_id,resume_version_id,
                 company,title,round_label,mode,question_count,status,
                 plan_json,progress_json,summary_json,started_at,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id, profile_id, args.application_id, posting_id,
                resume_version_id, company, title, round_label, args.mode,
                question_count, "started", json_dumps(plan),
                json_dumps({"questions": []}), json_dumps({}),
                stamp, stamp, stamp,
            ),
        )
        created = conn.execute(
            "SELECT * FROM interview_sessions WHERE id=?", (session_id,)
        ).fetchone()
    conn.close()
    emit(_interview_output(created), args.json)


def cmd_interview_progress(args):
    question_index = int(args.question_index)
    if not 1 <= question_index <= 20:
        fail("question-index 必须在 1 到 20 之间")
    scores = {
        name: _validate_score_component(name, getattr(args, name))
        for name in INTERVIEW_SCORE_LIMITS
    }
    improvement = redact((args.improvement_summary or "").strip())
    if not improvement:
        fail("必须提供非空的 improvement-summary")
    if len(improvement) > 1000:
        fail("improvement-summary 不能超过 1000 字")
    issue_tags = parse_csv(args.issue_tags)
    if len(issue_tags) > 10 or any(len(item) > 100 for item in issue_tags):
        fail("issue-tags 最多 10 项，每项不超过 100 字")
    retry_count = int(args.retry_count)
    if not 0 <= retry_count <= 10:
        fail("retry-count 必须在 0 到 10 之间")

    conn = connect(args.data_dir)
    row = conn.execute(
        "SELECT * FROM interview_sessions WHERE id=?", (args.id,)
    ).fetchone()
    if row is None:
        fail(f"找不到模拟面试会话：{args.id}")
    if row["status"] not in {"started", "in_progress"}:
        fail("只有进行中的模拟面试可以记录进度", 3)
    progress = json_loads(row["progress_json"], {"questions": []})
    if not isinstance(progress, dict):
        progress = {"questions": []}
    questions = progress.get("questions")
    if not isinstance(questions, list):
        questions = []
    total = sum(scores.values())
    entry = {
        "question_index": question_index,
        "score": total,
        "dimensions": scores,
        "issue_tags": [redact(item) for item in issue_tags],
        "improvement_summary": improvement,
        "retry_count": retry_count,
        "updated_at": now_iso(),
    }
    questions = [
        item for item in questions
        if not isinstance(item, dict) or item.get("question_index") != question_index
    ]
    questions.append(entry)
    questions.sort(key=lambda item: item.get("question_index", 0))
    progress["questions"] = questions
    _validate_interview_payload(progress, "progress")
    plan = json_loads(row["plan_json"], {})
    categories = plan.get("categories") if isinstance(plan, dict) else []
    if not isinstance(categories, list):
        categories = []
    if isinstance(plan, dict) and question_index > len(categories):
        while len(categories) < question_index:
            index = len(categories) + 1
            categories.append(
                {
                    "index": index,
                    "category": f"deep_dive_{index}",
                    "purpose": "根据上一题证据进行岗位相关追问",
                }
            )
        plan["categories"] = categories
        _validate_interview_payload(plan, "plan")
    stamp = now_iso()
    with transaction(conn):
        conn.execute(
            """UPDATE interview_sessions
               SET status='in_progress',question_count=?,plan_json=?,
                   progress_json=?,updated_at=?
               WHERE id=?""",
            (
                max(int(row["question_count"]), question_index),
                json_dumps(plan), json_dumps(progress), stamp, args.id,
            ),
        )
    conn.close()
    emit(
        {
            "interview_id": args.id,
            "status": "in_progress",
            "question_index": question_index,
            "score": total,
            "dimensions": scores,
        },
        args.json,
    )


def cmd_interview_complete(args):
    strengths = _parse_summary_list(args.strengths_json, "strengths-json")
    gaps = _parse_summary_list(args.gaps_json, "gaps-json")
    actions = _parse_summary_list(args.actions_json, "actions-json")
    followups = _parse_summary_list(args.followups_json, "followups-json")
    reverse_questions = _parse_summary_list(
        args.reverse_questions_json, "reverse-questions-json"
    )
    review_points = _parse_summary_list(args.review_points_json, "review-points-json")

    conn = connect(args.data_dir)
    row = conn.execute(
        "SELECT * FROM interview_sessions WHERE id=?", (args.id,)
    ).fetchone()
    if row is None:
        fail(f"找不到模拟面试会话：{args.id}")
    if row["status"] in {"completed", "abandoned"}:
        fail("该模拟面试已经结束", 3)
    progress = json_loads(row["progress_json"], {"questions": []})
    questions = progress.get("questions", []) if isinstance(progress, dict) else []
    scored = [
        item for item in questions
        if isinstance(item, dict) and isinstance(item.get("score"), (int, float))
    ]
    if not scored:
        fail("完成模拟面试前至少需要一条逐题评分")
    if not strengths or not gaps or not actions or not review_points:
        fail("完成模拟面试必须保存优势、缺口、训练行动和复习要点")
    if args.overall_score is None:
        overall_score = round(sum(item["score"] for item in scored) / len(scored))
    else:
        try:
            overall_score = int(args.overall_score)
        except (TypeError, ValueError):
            fail("overall-score 必须是整数")
        if not 0 <= overall_score <= 100:
            fail("overall-score 必须在 0 到 100 之间")
    dimension_averages = {}
    for name in INTERVIEW_SCORE_LIMITS:
        values = [
            item.get("dimensions", {}).get(name)
            for item in scored
            if isinstance(item.get("dimensions"), dict)
            and isinstance(item.get("dimensions", {}).get(name), (int, float))
        ]
        if values:
            dimension_averages[name] = round(sum(values) / len(values), 1)
    summary = {
        "completed_questions": len(scored),
        "dimension_averages": dimension_averages,
        "strengths": strengths,
        "gaps": gaps,
        "actions": actions,
        "likely_followups": followups,
        "reverse_questions": reverse_questions,
        "review_points": review_points,
    }
    _validate_interview_payload(summary, "summary")
    stamp = normalize_iso(args.completed_at or now_iso(), "completed-at")
    with transaction(conn):
        conn.execute(
            """UPDATE interview_sessions
               SET status='completed',summary_json=?,overall_score=?,
                   completed_at=?,updated_at=?
               WHERE id=?""",
            (json_dumps(summary), overall_score, stamp, stamp, args.id),
        )
        if row["application_id"]:
            conn.execute(
                """INSERT INTO application_events(
                     id,application_id,event_type,stage,note,occurred_at
                   ) VALUES(?,?,?,?,?,?)""",
                (
                    uid("event"), row["application_id"], "mock_interview_completed",
                    row["round_label"], f"模拟面试完成，综合分 {overall_score}", stamp,
                ),
            )
    conn.close()
    emit(
        {
            "interview_id": args.id,
            "status": "completed",
            "overall_score": overall_score,
            "summary": summary,
        },
        args.json,
    )


def cmd_interview_abandon(args):
    conn = connect(args.data_dir)
    row = conn.execute(
        "SELECT * FROM interview_sessions WHERE id=?", (args.id,)
    ).fetchone()
    if row is None:
        fail(f"找不到模拟面试会话：{args.id}")
    if row["status"] == "completed":
        fail("已完成的模拟面试不能标记为 abandoned", 3)
    summary = json_loads(row["summary_json"], {})
    if not isinstance(summary, dict):
        summary = {}
    if args.reason:
        summary["abandoned_reason"] = redact(args.reason[:1000])
    stamp = now_iso()
    with transaction(conn):
        conn.execute(
            """UPDATE interview_sessions
               SET status='abandoned',summary_json=?,completed_at=?,updated_at=?
               WHERE id=?""",
            (json_dumps(summary), stamp, stamp, args.id),
        )
    conn.close()
    emit({"interview_id": args.id, "status": "abandoned"}, args.json)


def cmd_interview_list(args):
    conn = connect(args.data_dir)
    clauses = []
    values = []
    if args.profile_id:
        clauses.append("profile_id=?")
        values.append(args.profile_id)
    if args.application_id:
        clauses.append("application_id=?")
        values.append(args.application_id)
    if args.status:
        if args.status not in INTERVIEW_STATUSES:
            fail("非法模拟面试状态")
        clauses.append("status=?")
        values.append(args.status)
    query = """SELECT id,profile_id,application_id,posting_id,resume_version_id,
                      company,title,round_label,mode,question_count,status,
                      overall_score,started_at,completed_at,created_at,updated_at
               FROM interview_sessions"""
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY started_at DESC"
    rows = conn.execute(query, values).fetchall()
    conn.close()
    emit(rows_dict(rows), True)


def cmd_interview_show(args):
    conn = connect(args.data_dir)
    row = conn.execute(
        "SELECT * FROM interview_sessions WHERE id=?", (args.id,)
    ).fetchone()
    conn.close()
    if row is None:
        fail(f"找不到模拟面试会话：{args.id}")
    emit(_interview_output(row), True)


def _next_digest(value=None, digest_time="09:00"):
    now = datetime.now(APP_TIMEZONE) if value is None else value.astimezone(APP_TIMEZONE)
    hour, minute = [int(x) for x in digest_time.split(":", 1)]
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.isoformat(timespec="seconds")


def cmd_due_list(args):
    conn = connect(args.data_dir)
    now = now_iso()
    rows = conn.execute("""SELECT r.*,p.company,p.title,p.city,p.deadline,p.application_url,m.score
      FROM recommendations r JOIN postings p ON p.id=r.posting_id
      LEFT JOIN matches m ON m.id=r.match_id
      WHERE r.status IN ('pending','preparing','snoozed') AND r.decision_due_at<=? AND p.status='active'
        AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.posting_id=p.id)
        AND (p.deadline IS NULL OR substr(p.deadline,1,10)>=date('now'))
      ORDER BY r.decision_due_at""", (now,)).fetchall()
    conn.close()
    emit(rows_dict(rows), True)


def _update_due(args, status, reason=None):
    conn = connect(args.data_dir)
    row = conn.execute("SELECT r.id,c.digest_time FROM recommendations r JOIN campaigns c ON c.id=r.campaign_id WHERE r.id=?", (args.id,)).fetchone()
    if row is None:
        fail(f"找不到推荐：{args.id}")
    with transaction(conn):
        if status == "snoozed":
            conn.execute("UPDATE recommendations SET status='snoozed',decision_due_at=?,last_progress_at=?,last_prompted_at=? WHERE id=?", (_next_digest(digest_time=row[1]), now_iso(), now_iso(), args.id))
        else:
            conn.execute("UPDATE recommendations SET status='archived',archived_reason=?,last_prompted_at=? WHERE id=?", (reason or "用户归档", now_iso(), args.id))
    conn.close()
    emit({"recommendation_id": args.id, "status": status}, args.json)


def cmd_due_snooze(args):
    _update_due(args, "snoozed")


def cmd_due_archive(args):
    _update_due(args, "archived", args.reason)


def cmd_export(args):
    conn = connect(args.data_dir)
    tables = [
        "profiles", "campaigns", "confirmed_facts", "postings",
        "posting_sources", "resume_versions", "matches", "recommendations",
        "form_sessions", "applications", "application_events",
        "interview_sessions", "discovery_runs", "source_yield",
    ]
    payload = {table: rows_dict(conn.execute(f"SELECT * FROM {table}").fetchall()) for table in tables}
    conn.close()
    destination = Path(args.output) if args.output else data_dir(args.data_dir) / f"export-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        destination.chmod(0o600)
    except OSError:
        pass
    emit({"output": str(destination), "tables": list(payload)}, args.json)


def cmd_digest_render(args):
    try:
        from digest import render
    except ImportError:  # pragma: no cover - package execution
        from .digest import render
    render(args)


def parser():
    ap = argparse.ArgumentParser(description="job-copilot 状态与数据 CLI")
    ap.add_argument("--data-dir", help="覆盖 JOB_COPILOT_DATA_DIR")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_init)
    p = sub.add_parser("status"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_status)

    p = sub.add_parser("profile"); ps = p.add_subparsers(dest="profile_command", required=True)
    q = ps.add_parser("show"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_profile_show)
    q = ps.add_parser("update"); q.add_argument("--id"); q.add_argument("--name-masked"); q.add_argument("--profile-json"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_profile_update)

    p = sub.add_parser("fact"); ps = p.add_subparsers(dest="fact_command", required=True)
    q = ps.add_parser("add"); q.add_argument("--id"); q.add_argument("--profile-id"); q.add_argument("--name-masked"); q.add_argument("--claim", required=True); q.add_argument("--detail", required=True); q.add_argument("--stage", required=True); q.add_argument("--source-resume-version-id"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_fact_add)
    q = ps.add_parser("list"); q.add_argument("--profile-id"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_fact_list)

    p = sub.add_parser("campaign"); ps = p.add_subparsers(dest="campaign_command", required=True)
    q = ps.add_parser("create"); q.add_argument("--id"); q.add_argument("--profile-id"); q.add_argument("--name-masked"); q.add_argument("--name", required=True); q.add_argument("--route", required=True); q.add_argument("--directions"); q.add_argument("--cities"); q.add_argument("--priority-companies"); q.add_argument("--excluded-companies"); q.add_argument("--preferences-json"); q.add_argument("--daily-quota", default=5, type=int); q.add_argument("--min-match-score", default=70, type=int); q.add_argument("--digest-time", default="09:00"); q.add_argument("--activate", action="store_true"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_campaign_create)
    q = ps.add_parser("list"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_campaign_list)
    q = ps.add_parser("activate"); q.add_argument("id"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_campaign_activate)
    q = ps.add_parser("update"); q.add_argument("id"); q.add_argument("--name"); q.add_argument("--directions"); q.add_argument("--cities"); q.add_argument("--priority-companies"); q.add_argument("--excluded-companies"); q.add_argument("--daily-quota", type=int); q.add_argument("--min-match-score", type=int); q.add_argument("--digest-time"); q.add_argument("--preferences-json"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_campaign_update)

    p = sub.add_parser("posting"); ps = p.add_subparsers(dest="posting_command", required=True)
    q = ps.add_parser("import-json"); q.add_argument("--campaign", required=True); q.add_argument("--input", required=True); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_posting_import)
    q = ps.add_parser("list"); q.add_argument("--campaign", required=True); q.add_argument("--status"); q.add_argument("--route"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_posting_list)
    q = ps.add_parser("archive"); q.add_argument("id"); q.add_argument("--reason"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_posting_archive)
    q = ps.add_parser("verify"); q.add_argument("id"); q.add_argument("--tier", required=True); q.add_argument("--platform"); q.add_argument("--official-url"); q.add_argument("--application-url"); q.add_argument("--evidence"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_posting_verify)

    p = sub.add_parser("match"); ps = p.add_subparsers(dest="match_command", required=True)
    q = ps.add_parser("pending"); q.add_argument("--campaign"); q.add_argument("--resume-version-id"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_match_pending)
    q = ps.add_parser("record"); q.add_argument("--input", required=True); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_match_record)
    q = ps.add_parser("list"); q.add_argument("--posting-id"); q.add_argument("--resume-version-id"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_match_list)

    p = sub.add_parser("resume"); ps = p.add_subparsers(dest="resume_command", required=True)
    q = ps.add_parser("import"); q.add_argument("--file", required=True); q.add_argument("--id"); q.add_argument("--profile-id"); q.add_argument("--name-masked"); q.add_argument("--kind", default="base", choices=["base", "tailored"]); q.add_argument("--label"); q.add_argument("--photo"); q.add_argument("--tags"); q.add_argument("--honesty-checked", action="store_true"); q.add_argument("--set-base", action="store_true"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_resume_import)
    q = ps.add_parser("register"); q.add_argument("--id", required=True); q.add_argument("--profile-id"); q.add_argument("--name-masked"); q.add_argument("--kind", required=True, choices=["base", "tailored"]); q.add_argument("--label", required=True); q.add_argument("--base-version-id"); q.add_argument("--target-posting-id"); q.add_argument("--original-path"); q.add_argument("--text-path"); q.add_argument("--html-path"); q.add_argument("--pdf-path"); q.add_argument("--photo-path"); q.add_argument("--hashes-json"); q.add_argument("--tags"); q.add_argument("--score-before", type=int); q.add_argument("--score-after", type=int); q.add_argument("--honesty-checked", action="store_true"); q.add_argument("--active-base", action="store_true"); q.add_argument("--created-at"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_resume_register)
    q = ps.add_parser("list"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_resume_list)
    q = ps.add_parser("set-base"); q.add_argument("id"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_resume_set_base)

    p = sub.add_parser("form"); ps = p.add_subparsers(dest="form_command", required=True)
    q = ps.add_parser("start"); q.add_argument("--id"); q.add_argument("--posting-id", required=True); q.add_argument("--resume-version-id", required=True); q.add_argument("--form-url", required=True); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_form_start)
    q = ps.add_parser("update"); q.add_argument("id"); q.add_argument("--status", required=True); q.add_argument("--manifest-json"); q.add_argument("--blocked-fields-json"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_form_update)
    q = ps.add_parser("blocked"); q.add_argument("id"); q.add_argument("--manifest-json"); q.add_argument("--blocked-fields-json"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_form_blocked)
    q = ps.add_parser("ready"); q.add_argument("id"); q.add_argument("--manifest-json"); q.add_argument("--blocked-fields-json"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_form_ready)

    p = sub.add_parser("application"); ps = p.add_subparsers(dest="application_command", required=True)
    q = ps.add_parser("mark-submitted"); q.add_argument("--id"); q.add_argument("--posting-id", required=True); q.add_argument("--resume-version-id", required=True); q.add_argument("--form-session-id"); q.add_argument("--channel", default="官网"); q.add_argument("--applied-at"); q.add_argument("--next-action-at"); q.add_argument("--note"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_application_mark_submitted)
    q = ps.add_parser("stage"); q.add_argument("--id", required=True); q.add_argument("--stage", required=True); q.add_argument("--date"); q.add_argument("--next-action-at"); q.add_argument("--note"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_application_stage)
    q = ps.add_parser("check-status"); q.add_argument("--id", required=True); q.add_argument("--result", required=True, choices=["no-update", "updated", "stop"]); q.add_argument("--stage"); q.add_argument("--date"); q.add_argument("--next-action-at"); q.add_argument("--note"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_application_check_status)
    q = ps.add_parser("list"); q.add_argument("--open-only", action="store_true"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_application_list)
    q = ps.add_parser("stats"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_application_stats)

    p = sub.add_parser("interview"); ps = p.add_subparsers(dest="interview_command", required=True)
    q = ps.add_parser("start"); q.add_argument("--id"); q.add_argument("--profile-id"); q.add_argument("--application-id"); q.add_argument("--posting-id"); q.add_argument("--resume-version-id"); q.add_argument("--company"); q.add_argument("--title"); q.add_argument("--route", choices=["campus", "social"]); q.add_argument("--round-label", default="未注明"); q.add_argument("--focus", default="综合"); q.add_argument("--mode", default="coached", choices=["coached"]); q.add_argument("--question-count", type=int, default=6); q.add_argument("--plan-json"); q.add_argument("--started-at"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_interview_start)
    q = ps.add_parser("progress"); q.add_argument("--id", required=True); q.add_argument("--question-index", required=True, type=int); q.add_argument("--relevance", required=True, type=int); q.add_argument("--evidence", required=True, type=int); q.add_argument("--structure", required=True, type=int); q.add_argument("--role-fit", dest="role_fit", required=True, type=int); q.add_argument("--clarity", required=True, type=int); q.add_argument("--issue-tags"); q.add_argument("--improvement-summary", required=True); q.add_argument("--retry-count", type=int, default=0); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_interview_progress)
    q = ps.add_parser("complete"); q.add_argument("--id", required=True); q.add_argument("--overall-score", type=int); q.add_argument("--strengths-json", default="[]"); q.add_argument("--gaps-json", default="[]"); q.add_argument("--actions-json", default="[]"); q.add_argument("--followups-json", default="[]"); q.add_argument("--reverse-questions-json", default="[]"); q.add_argument("--review-points-json", default="[]"); q.add_argument("--completed-at"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_interview_complete)
    q = ps.add_parser("abandon"); q.add_argument("--id", required=True); q.add_argument("--reason"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_interview_abandon)
    q = ps.add_parser("list"); q.add_argument("--profile-id"); q.add_argument("--application-id"); q.add_argument("--status", choices=sorted(INTERVIEW_STATUSES)); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_interview_list)
    q = ps.add_parser("show"); q.add_argument("--id", required=True); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_interview_show)

    p = sub.add_parser("due"); ps = p.add_subparsers(dest="due_command", required=True)
    q = ps.add_parser("list"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_due_list)
    q = ps.add_parser("snooze"); q.add_argument("id"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_due_snooze)
    q = ps.add_parser("archive"); q.add_argument("id"); q.add_argument("--reason"); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_due_archive)

    p = sub.add_parser("digest"); ps = p.add_subparsers(dest="digest_command", required=True)
    q = ps.add_parser("render"); q.add_argument("--campaign"); q.add_argument("--data-dir", default=argparse.SUPPRESS); q.set_defaults(func=cmd_digest_render)

    p = sub.add_parser("export"); p.add_argument("--output"); p.add_argument("--json", action="store_true"); p.set_defaults(func=cmd_export)
    return ap


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        args.func(args)
    except sqlite3.IntegrityError as exc:
        fail(f"数据库约束冲突：{exc}", 3)
    except (OSError, ValueError, RuntimeError) as exc:
        fail(str(exc), 2)


if __name__ == "__main__":
    main()
