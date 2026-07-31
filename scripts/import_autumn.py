#!/usr/bin/env python3
"""Explicit, dry-run-first importer for the older autumn tracker JSON files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from db import connect, data_dir, json_dumps, now_iso, transaction, validate_profile_json
except ImportError:
    from .db import connect, data_dir, json_dumps, now_iso, transaction, validate_profile_json


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON 无效：{path}: {exc}")


def discover_files(root: Path):
    return {
        "config": root / "config.json",
        "profile": root / "resumes" / "profile.json",
        "index": root / "resumes" / "index.json",
        "postings": root / "state" / "seen_postings.json",
        "applications": root / "state" / "applications.json",
    }


def dry_run(args):
    files = discover_files(Path(args.autumn_dir))
    missing = [key for key, path in files.items() if not path.exists()]
    payload = {"files": {key: str(path) for key, path in files.items() if path.exists()}, "counts": {}, "warnings": []}
    payload["warnings"].extend(f"旧 Skill 缺少 {key} 文件，使用默认空数据" for key in missing)
    profile = load(files["profile"], {})
    index = load(files["index"], {"versions": []})
    state = load(files["postings"], {"postings": {}})
    apps = load(files["applications"], {"applications": {}})
    payload["counts"] = {
        "profiles": 1 if profile else 0,
        "resume_versions": len(index.get("versions", [])),
        "postings": len(state.get("postings", {})),
        "applications": len(apps.get("applications", {})),
    }
    if profile and not profile.get("name_masked"):
        payload["warnings"].append("profile.json 缺少 name_masked，导入时使用“求职者”")
    for index, version in enumerate(index.get("versions", [])):
        if not version.get("id"):
            payload["warnings"].append(f"第 {index + 1} 个简历版本缺少 id，将生成默认 ID")
    for key, posting in state.get("postings", {}).items():
        if not posting.get("company") or not posting.get("title"):
            payload["warnings"].append(f"岗位 {key} 缺少公司或标题，将使用未注明默认值")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def import_data(args):
    files = discover_files(Path(args.autumn_dir))
    config = load(files["config"], {})
    profile = load(files["profile"], {})
    index = load(files["index"], {"versions": []})
    state = load(files["postings"], {"postings": {}})
    apps = load(files["applications"], {"applications": {}})
    config_warning = False
    try:
        validate_profile_json(config)
    except ValueError:
        config = {}
        config_warning = True
    conn = connect(args.data_dir)
    try:
        validate_profile_json(profile)
    except ValueError as exc:
        raise SystemExit(f"旧 profile 含禁止保存字段：{exc}")
    warnings = []
    if config_warning:
        warnings.append("旧 config 含禁止保存字段，已丢弃该配置")
    posting_ids = {}
    with transaction(conn):
        profile_id = "profile-imported-autumn"
        stamp = now_iso()
        conn.execute("INSERT OR IGNORE INTO profiles(id,name_masked,application_profile_json,created_at,updated_at) VALUES(?,?,?,?,?)", (profile_id, profile.get("name_masked", "求职者"), json_dumps(profile), stamp, stamp))
        route = "campus"
        campaign_id = "campaign-imported-autumn"
        conn.execute("INSERT OR IGNORE INTO campaigns(id,profile_id,name,route,active,directions_json,preferences_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (campaign_id, profile_id, "导入的秋招 Campaign", route, 0, json_dumps(profile.get("intent", {}).get("directions", [])), json_dumps(config), stamp, stamp))
        for index, version in enumerate(index.get("versions", [])):
            version_id = version.get("id") or f"autumn-version-{index + 1}"
            conn.execute("INSERT OR IGNORE INTO resume_versions(id,profile_id,kind,label,original_path,text_path,html_path,pdf_path,base_version_id,score_before,score_after,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (version_id, profile_id, version.get("kind", "base"), version.get("label", "导入版本"), (version.get("files") or {}).get("original"), (version.get("files") or {}).get("txt"), (version.get("files") or {}).get("html"), (version.get("files") or {}).get("pdf"), version.get("base_version"), version.get("score_before"), version.get("score_after"), version.get("created_at") or stamp))
            if not version.get("id"):
                warnings.append(f"第 {index + 1} 个简历版本缺少 id，已使用 {version_id}")
        for key, posting in state.get("postings", {}).items():
            posting_id = posting.get("id") or f"autumn-{key}"
            company = posting.get("company") or "未注明公司"
            title = posting.get("title") or "未注明岗位"
            if not posting.get("company") or not posting.get("title"):
                warnings.append(f"岗位 {key} 缺少公司或标题，已使用默认值")
            conn.execute("INSERT OR IGNORE INTO postings(id,campaign_id,canonical_key,company,title,city,route,employment_type,official_url,application_url,deadline,status,first_seen_at,last_verified_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (posting_id, campaign_id, f"imported|{key}", company, title, posting.get("city", "未注明"), route, None, posting.get("source_url"), posting.get("source_url"), posting.get("deadline"), "active" if not posting.get("expired") else "expired", posting.get("first_seen", stamp), posting.get("last_confirmed")))
            posting_ids[key] = posting_id
            if posting.get("id"):
                posting_ids[posting["id"]] = posting_id
        imported_apps = 0
        for app_id, app in apps.get("applications", {}).items():
            posting_id = posting_ids.get(app.get("posting_id"))
            if not posting_id:
                warnings.append(f"投递 {app_id} 找不到对应岗位，已跳过")
                continue
            resume_id = app.get("resume_version") or "autumn-version-unknown"
            if not conn.execute("SELECT 1 FROM resume_versions WHERE id=?", (resume_id,)).fetchone():
                warnings.append(f"投递 {app_id} 缺少简历版本，已跳过")
                continue
            conn.execute("INSERT OR IGNORE INTO applications(id,posting_id,resume_version_id,channel,applied_at,current_stage,closed,outcome,next_action_at,last_update_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (f"autumn-{app_id}", posting_id, resume_id, app.get("channel", "未知"), app.get("applied_at", stamp), app.get("stage", "已投递"), int(app.get("closed", False)), app.get("outcome"), app.get("next_action_at"), app.get("applied_at", stamp)))
            imported_apps += 1
    conn.close()
    print(json.dumps({"imported": True, "campaign_id": campaign_id, "applications": imported_apps, "warnings": warnings}, ensure_ascii=False))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--autumn-dir", required=True)
    ap.add_argument("--data-dir")
    ap.add_argument("--apply", action="store_true", help="确认后才真正写入")
    args = ap.parse_args(argv)
    if not args.apply:
        dry_run(args)
    else:
        import_data(args)


if __name__ == "__main__":
    main()
