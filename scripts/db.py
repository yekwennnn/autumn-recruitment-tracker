#!/usr/bin/env python3
"""SQLite and filesystem primitives for job-copilot.

This module is intentionally dependency-free.  All state-changing commands in
the skill go through these helpers so migrations, timestamps and redaction are
consistent across the resume, posting and application workflows.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SCHEMA_VERSION = 2
APP_TIMEZONE = ZoneInfo("Asia/Shanghai")
DEFAULT_CONFIG = {
    "schema_version": 2,
    "timezone": "Asia/Shanghai",
    "daily_digest_time": "09:00",
    "daily_quota_default": 5,
    "daily_quota_max": 20,
    "min_match_score_default": 70,
    "decision_after_hours": 24,
    "application_followup_days_default": 3,
}
SENSITIVE_PROFILE_KEY_PARTS = (
    "password", "passwd", "cookie", "token", "captcha", "验证码", "sms", "短信",
    "身份证", "id_number", "identity", "bank", "银行卡", "signature", "电子签名",
    "health", "健康", "disability", "残疾", "criminal", "犯罪", "credit", "征信",
    "consent", "法律", "truth", "真实性", "承诺", "background_check",
)


def skill_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def data_dir(value: str | os.PathLike[str] | None = None) -> Path:
    """Return the configured runtime directory without using a fixed home path."""
    if value:
        return Path(value).expanduser().resolve()
    configured = os.environ.get("JOB_COPILOT_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return skill_dir() / "data"


def ensure_layout(root: Path) -> Path:
    root = root.resolve()
    directories = [root / name for name in ("backups", "originals", "photos", "resumes", "tmp")]
    directories.append(root / "resumes" / "versions")
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def config_path(root: Path | None = None) -> Path:
    return data_dir(root) / "config.json"


def ensure_config(root: Path | None = None) -> Path:
    root = ensure_layout(data_dir(root))
    path = root / "config.json"
    if not path.exists():
        source = skill_dir() / "config.example.json"
        content = source.read_text(encoding="utf-8") if source.exists() else json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path


def load_config(root: Path | None = None) -> dict:
    path = ensure_config(root)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取配置文件 {path}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeError(f"配置文件 {path} 顶层必须是 JSON 对象")
    merged = dict(DEFAULT_CONFIG)
    merged.update(loaded)
    merged["schema_version"] = SCHEMA_VERSION
    if merged != loaded:
        save_config(merged, root)
    return merged


def save_config(config: dict, root: Path | None = None) -> Path:
    path = ensure_config(root)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone(APP_TIMEZONE).isoformat(timespec="seconds")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=APP_TIMEZONE)
    return parsed


def hours_from(value: str, hours: float) -> str:
    return (parse_time(value) + timedelta(hours=hours)).astimezone(APP_TIMEZONE).isoformat(timespec="seconds")


def json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value, default):
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def validate_profile_json(value):
    """Reject fields that must never be persisted in application profiles."""
    if not isinstance(value, dict):
        raise ValueError("application profile 必须是 JSON 对象")
    for key, item in value.items():
        key_text = str(key).lower()
        if any(part.lower() in key_text for part in SENSITIVE_PROFILE_KEY_PARTS):
            raise ValueError(f"application profile 含禁止保存字段：{key}")
        if isinstance(item, dict):
            validate_profile_json(item)
        elif isinstance(item, list):
            for nested in item:
                if isinstance(nested, dict):
                    validate_profile_json(nested)
    return value


def hash_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def hash_text(text: str) -> str:
    return hash_bytes(text.encode("utf-8"))


def hash_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_component(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"\s+", " ", value)


def canonicalize_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value.strip())
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))
    except ValueError:
        return value.strip()


def canonical_key(company: str, title: str, city: str, url: str | None = None, official_job_id: str | None = None) -> str:
    company_key = normalize_component(company)
    if official_job_id:
        return f"{company_key}|{normalize_component(official_job_id)}"
    return "|".join((
        company_key,
        normalize_component(title),
        normalize_component(city or "未注明"),
        canonicalize_url(url),
    ))


def redact(value: str) -> str:
    """Redact common contact and credential patterns before logging."""
    text = str(value or "")
    text = re.sub(r"(?i)(password|passwd|token|cookie|验证码|身份证号)\s*[:=：]\s*[^\s,;]+", r"\1=[REDACTED]", text)
    text = re.sub(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)", r"\1****\2", text)
    text = re.sub(r"\b([\w.+-])[\w.+-]*(@[\w.-]+)\b", r"\1***\2", text)
    text = re.sub(r"(?<!\d)(\d{6,20})(?!\d)", "[REDACTED_NUMBER]", text)
    return text


def redact_structure(value, sensitive=False):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key).lower()
            key_sensitive = sensitive or any(part.lower() in key_text for part in SENSITIVE_PROFILE_KEY_PARTS) or key_text in {"phone", "mobile", "tel", "email", "e-mail"}
            result[key] = redact_structure(item, key_sensitive)
        return result
    if isinstance(value, list):
        return [redact_structure(item, sensitive) for item in value]
    if isinstance(value, str):
        looks_sensitive = sensitive or "@" in value or bool(re.fullmatch(r"1[3-9]\d{9}", value)) or bool(re.fullmatch(r"\d{6,20}", value))
        if sensitive:
            redacted = redact(value)
            return redacted if redacted != value else "[REDACTED]"
        return redact(value) if looks_sensitive else value
    return value


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS profiles (
  id TEXT PRIMARY KEY,
  name_masked TEXT NOT NULL,
  application_profile_json TEXT NOT NULL DEFAULT '{}',
  generated_from_resume_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campaigns (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id),
  name TEXT NOT NULL,
  route TEXT NOT NULL CHECK(route IN ('campus','social')),
  active INTEGER NOT NULL DEFAULT 0 CHECK(active IN (0,1)),
  directions_json TEXT NOT NULL DEFAULT '[]',
  cities_json TEXT NOT NULL DEFAULT '[]',
  priority_companies_json TEXT NOT NULL DEFAULT '[]',
  excluded_companies_json TEXT NOT NULL DEFAULT '[]',
  preferences_json TEXT NOT NULL DEFAULT '{}',
  daily_quota INTEGER NOT NULL DEFAULT 5 CHECK(daily_quota BETWEEN 1 AND 20),
  min_match_score INTEGER NOT NULL DEFAULT 70 CHECK(min_match_score BETWEEN 0 AND 100),
  digest_time TEXT NOT NULL DEFAULT '09:00',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_campaign_active ON campaigns(active) WHERE active=1;
CREATE TABLE IF NOT EXISTS confirmed_facts (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id),
  claim TEXT NOT NULL,
  detail TEXT NOT NULL,
  stage TEXT NOT NULL,
  source_resume_version_id TEXT,
  confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS postings (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  canonical_key TEXT NOT NULL,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  city TEXT NOT NULL DEFAULT '未注明',
  route TEXT NOT NULL CHECK(route IN ('campus','social')),
  employment_type TEXT,
  official_url TEXT,
  application_url TEXT,
  jd_text TEXT,
  jd_hash TEXT,
  deadline TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  first_seen_at TEXT NOT NULL,
  last_verified_at TEXT,
  archived_at TEXT,
  UNIQUE(campaign_id, canonical_key)
);
CREATE INDEX IF NOT EXISTS ix_postings_status_deadline ON postings(campaign_id, status, deadline);
CREATE TABLE IF NOT EXISTS posting_sources (
  id TEXT PRIMARY KEY,
  posting_id TEXT NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
  tier TEXT NOT NULL CHECK(tier IN ('A','B','C')),
  platform TEXT NOT NULL,
  url TEXT NOT NULL,
  evidence TEXT,
  discovered_at TEXT NOT NULL,
  verified_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_sources_posting_tier ON posting_sources(posting_id, tier);
CREATE TABLE IF NOT EXISTS resume_versions (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id),
  kind TEXT NOT NULL CHECK(kind IN ('base','tailored')),
  base_version_id TEXT,
  target_posting_id TEXT REFERENCES postings(id),
  label TEXT NOT NULL,
  original_path TEXT,
  text_path TEXT,
  html_path TEXT,
  pdf_path TEXT,
  photo_path TEXT,
  hashes_json TEXT NOT NULL DEFAULT '{}',
  tags_json TEXT NOT NULL DEFAULT '[]',
  score_before INTEGER,
  score_after INTEGER,
  honesty_checked INTEGER NOT NULL DEFAULT 0 CHECK(honesty_checked IN (0,1)),
  active_base INTEGER NOT NULL DEFAULT 0 CHECK(active_base IN (0,1)),
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_resume_active_base ON resume_versions(profile_id) WHERE active_base=1;
CREATE TABLE IF NOT EXISTS matches (
  id TEXT PRIMARY KEY,
  posting_id TEXT NOT NULL REFERENCES postings(id) ON DELETE CASCADE,
  resume_version_id TEXT NOT NULL REFERENCES resume_versions(id),
  eligible INTEGER NOT NULL CHECK(eligible IN (0,1)),
  score INTEGER,
  coverage INTEGER NOT NULL CHECK(coverage BETWEEN 0 AND 100),
  confidence TEXT NOT NULL CHECK(confidence IN ('high','medium','low')),
  hard_failures_json TEXT NOT NULL DEFAULT '[]',
  dimensions_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  gaps_json TEXT NOT NULL DEFAULT '[]',
  actions_json TEXT NOT NULL DEFAULT '[]',
  jd_hash TEXT,
  evaluated_at TEXT NOT NULL,
  UNIQUE(posting_id, resume_version_id, jd_hash)
);
CREATE TABLE IF NOT EXISTS recommendations (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  posting_id TEXT NOT NULL REFERENCES postings(id),
  match_id TEXT NOT NULL REFERENCES matches(id),
  resume_version_id TEXT NOT NULL REFERENCES resume_versions(id),
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','preparing','snoozed','applied','archived','expired')),
  recommended_at TEXT NOT NULL,
  decision_due_at TEXT NOT NULL,
  last_progress_at TEXT,
  last_prompted_at TEXT,
  archived_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_recommendation_due ON recommendations(status, decision_due_at);
CREATE TABLE IF NOT EXISTS form_sessions (
  id TEXT PRIMARY KEY,
  posting_id TEXT NOT NULL REFERENCES postings(id),
  resume_version_id TEXT NOT NULL REFERENCES resume_versions(id),
  form_url TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('started','blocked','draft_filled','ready_for_review','submission_confirmed','abandoned')),
  redacted_manifest_json TEXT NOT NULL DEFAULT '{}',
  blocked_fields_json TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL,
  filled_at TEXT,
  confirmation_observed_at TEXT
);
CREATE TABLE IF NOT EXISTS applications (
  id TEXT PRIMARY KEY,
  posting_id TEXT NOT NULL REFERENCES postings(id),
  resume_version_id TEXT NOT NULL REFERENCES resume_versions(id),
  form_session_id TEXT REFERENCES form_sessions(id),
  channel TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  current_stage TEXT NOT NULL,
  closed INTEGER NOT NULL DEFAULT 0 CHECK(closed IN (0,1)),
  outcome TEXT,
  next_action_at TEXT,
  last_update_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_applications_stage_action ON applications(current_stage, next_action_at);
CREATE TABLE IF NOT EXISTS application_events (
  id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
  stage TEXT,
  note TEXT,
  occurred_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_sessions (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES profiles(id),
  application_id TEXT REFERENCES applications(id),
  posting_id TEXT REFERENCES postings(id),
  resume_version_id TEXT REFERENCES resume_versions(id),
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  round_label TEXT NOT NULL DEFAULT '未注明',
  mode TEXT NOT NULL DEFAULT 'coached' CHECK(mode IN ('coached')),
  question_count INTEGER NOT NULL DEFAULT 6 CHECK(question_count BETWEEN 1 AND 20),
  status TEXT NOT NULL CHECK(status IN ('started','in_progress','completed','abandoned')),
  plan_json TEXT NOT NULL DEFAULT '{}',
  progress_json TEXT NOT NULL DEFAULT '{}',
  summary_json TEXT NOT NULL DEFAULT '{}',
  overall_score INTEGER CHECK(overall_score BETWEEN 0 AND 100),
  started_at TEXT NOT NULL,
  completed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_interview_profile_status
  ON interview_sessions(profile_id, status, started_at);
CREATE INDEX IF NOT EXISTS ix_interview_application_started
  ON interview_sessions(application_id, started_at);
CREATE TABLE IF NOT EXISTS discovery_runs (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  mode TEXT NOT NULL,
  lanes_json TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL,
  completed_at TEXT,
  result_count INTEGER NOT NULL DEFAULT 0,
  error_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS source_yield (
  campaign_id TEXT NOT NULL REFERENCES campaigns(id),
  lane_id TEXT NOT NULL,
  runs INTEGER NOT NULL DEFAULT 0,
  new_count INTEGER NOT NULL DEFAULT 0,
  qualified_count INTEGER NOT NULL DEFAULT 0,
  zero_streak INTEGER NOT NULL DEFAULT 0,
  last_run_at TEXT,
  PRIMARY KEY(campaign_id, lane_id)
);
"""


def _backup_if_needed(
    conn: sqlite3.Connection,
    root: Path,
    db_path: Path,
    current_version: int,
) -> None:
    user_tables = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchone()[0]
    if current_version < SCHEMA_VERSION and user_tables and db_path.exists() and db_path.stat().st_size:
        backup = root / "backups" / f"job-copilot-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
        backup_conn = sqlite3.connect(backup)
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()
        try:
            backup.chmod(0o600)
        except OSError:
            pass


def migrate(conn: sqlite3.Connection, root: Path, db_path: Path) -> None:
    current = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current > SCHEMA_VERSION:
        raise RuntimeError(f"数据库版本 {current} 高于当前 Skill 支持的 {SCHEMA_VERSION}")
    if current < SCHEMA_VERSION:
        _backup_if_needed(conn, root, db_path, current)
        conn.executescript(SCHEMA_SQL)
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.commit()


def connect(root: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    root_path = ensure_layout(data_dir(root))
    ensure_config(root_path)
    db_path = root_path / "job-copilot.sqlite3"
    conn = sqlite3.connect(db_path, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    migrate(conn, root_path, db_path)
    try:
        db_path.chmod(0o600)
    except OSError:
        pass
    return conn


@contextlib.contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def rows_dict(rows) -> list[dict]:
    return [dict(row) for row in rows]


if __name__ == "__main__":
    connection = connect()
    print(json.dumps({"db": str(data_dir() / 'job-copilot.sqlite3'), "schema_version": SCHEMA_VERSION}, ensure_ascii=False))
    connection.close()
