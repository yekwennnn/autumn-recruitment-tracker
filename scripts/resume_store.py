#!/usr/bin/env python3
"""Manage the resume archive (resumes/index.json). Sole writer of that file.

Subcommands (all take --resumes <dir>, callers pass $SKILL_DIR/resumes):
  status           Print archive summary as JSON.
  import-original  Copy a user-provided resume file into originals/.
  register         Upsert a resume version entry in index.json.
  list             Human-readable table (or --json) of all versions.
  pick-base        Deterministically pick the best base version for a JD.
"""
import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

EMPTY_INDEX = {"schema_version": 1, "active_base": None, "versions": []}


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


def index_path(resumes_dir):
    return Path(resumes_dir) / "index.json"


def load_index(resumes_dir):
    return load_json(index_path(resumes_dir), json.loads(json.dumps(EMPTY_INDEX)))


def find_version(index, vid):
    for v in index.get("versions", []):
        if v.get("id") == vid:
            return v
    return None


def cmd_status(args):
    resumes = Path(args.resumes)
    idx_file = index_path(resumes)
    index = load_index(resumes)
    originals = resumes / "originals"
    originals_count = sum(1 for p in originals.iterdir() if p.is_file()) if originals.is_dir() else 0
    print(json.dumps({
        "exists": idx_file.exists(),
        "active_base": index.get("active_base"),
        "version_count": len(index.get("versions", [])),
        "originals_count": originals_count,
        "profile_exists": (resumes / "profile.json").exists(),
    }, ensure_ascii=False))


def cmd_import_original(args):
    resumes = Path(args.resumes)
    originals = resumes / "originals"
    originals.mkdir(parents=True, exist_ok=True)
    src = Path(args.file)
    if not src.exists():
        sys.stderr.write(f"文件不存在：{src}\n")
        sys.exit(2)
    stamp = date.today().strftime("%Y%m%d")
    base_name = f"{stamp}-{src.name}"
    dest = originals / base_name
    n = 2
    while dest.exists():
        dest = originals / f"{stamp}-{n}-{src.name}"
        n += 1
    shutil.copy2(src, dest)
    print(str(dest.relative_to(resumes)))


def cmd_register(args):
    resumes = Path(args.resumes)
    resumes.mkdir(parents=True, exist_ok=True)
    index = load_index(resumes)
    entry = find_version(index, args.id)
    if entry is None:
        entry = {
            "id": args.id, "kind": args.kind, "label": args.label,
            "created_at": datetime.now().astimezone().isoformat(),
            "files": {"original": None, "txt": None, "html": None, "pdf": None},
            "target": None, "base_version": None, "tags": [],
            "score_before": None, "score_after": None,
        }
        index.setdefault("versions", []).append(entry)
    entry["kind"] = args.kind
    entry["label"] = args.label
    for key in ("original", "txt", "html", "pdf"):
        val = getattr(args, key)
        if val is not None:
            entry.setdefault("files", {})[key] = val
    if args.company or args.title:
        entry["target"] = {
            "company": args.company or "", "title": args.title or "",
            "posting_id": args.posting_id, "jd_url": args.jd_url or "",
        }
    if args.base is not None:
        entry["base_version"] = args.base
    if args.tags is not None:
        entry["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if args.score_before is not None:
        entry["score_before"] = args.score_before
    if args.score_after is not None:
        entry["score_after"] = args.score_after
    if args.set_active:
        index["active_base"] = args.id
    save_json(index_path(resumes), index)
    print(f"registered {args.id}")


def cmd_list(args):
    index = load_index(Path(args.resumes))
    versions = index.get("versions", [])
    if args.json:
        print(json.dumps(versions, ensure_ascii=False, indent=2))
        return
    active = index.get("active_base")
    if not versions:
        print("（档案为空，尚未注册任何简历版本）")
        return
    for v in versions:
        star = " *active" if v.get("id") == active else ""
        target = v.get("target") or {}
        target_str = f" -> {target.get('company', '')}·{target.get('title', '')}" if target else ""
        score = v.get("score_after")
        score_str = f" [{score}分]" if score is not None else ""
        created = (v.get("created_at") or "")[:10]
        print(f"{v.get('id')}  {v.get('kind')}  {v.get('label')}  {created}{score_str}{target_str}{star}")


def cmd_pick_base(args):
    resumes = Path(args.resumes)
    index = load_index(resumes)
    versions = index.get("versions", [])
    active = index.get("active_base")
    if not versions:
        print(json.dumps({"id": None, "score": 0, "reason": "档案为空"}, ensure_ascii=False))
        return
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    best = None
    best_key = None
    for v in versions:
        tags = [t.lower() for t in v.get("tags", [])]
        txt_rel = (v.get("files") or {}).get("txt")
        txt = ""
        if txt_rel:
            txt_file = resumes / txt_rel
            if txt_file.exists():
                txt = txt_file.read_text(encoding="utf-8", errors="replace").lower()
        score = 0
        hit_tags = []
        for kw in keywords:
            k = kw.lower()
            if any(k in t or t in k for t in tags):
                score += 3
                hit_tags.append(kw)
            elif k in txt:
                score += 1
        is_active = 1 if v.get("id") == active else 0
        key = (score, is_active, v.get("created_at") or "")
        if best_key is None or key > best_key:
            best_key = key
            best = (v, score, hit_tags)
    v, score, hit_tags = best
    if score == 0 and active:
        fallback = find_version(index, active) or v
        print(json.dumps({"id": fallback.get("id"), "score": 0,
                          "reason": "关键词均未命中，回退活跃基底"}, ensure_ascii=False))
        return
    reason = f"命中 tags：{'、'.join(hit_tags)}" if hit_tags else "命中简历全文关键词"
    print(json.dumps({"id": v.get("id"), "score": score, "reason": reason}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status")
    p.add_argument("--resumes", required=True)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("import-original")
    p.add_argument("--resumes", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_import_original)

    p = sub.add_parser("register")
    p.add_argument("--resumes", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--kind", required=True, choices=["base", "tailored"])
    p.add_argument("--label", required=True)
    p.add_argument("--original")
    p.add_argument("--txt")
    p.add_argument("--html")
    p.add_argument("--pdf")
    p.add_argument("--company")
    p.add_argument("--title")
    p.add_argument("--posting-id", dest="posting_id")
    p.add_argument("--jd-url", dest="jd_url")
    p.add_argument("--base")
    p.add_argument("--score-before", dest="score_before", type=int)
    p.add_argument("--score-after", dest="score_after", type=int)
    p.add_argument("--tags")
    p.add_argument("--set-active", dest="set_active", action="store_true")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("list")
    p.add_argument("--resumes", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("pick-base")
    p.add_argument("--resumes", required=True)
    p.add_argument("--keywords", required=True)
    p.set_defaults(func=cmd_pick_base)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
