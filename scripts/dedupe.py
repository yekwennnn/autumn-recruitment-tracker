#!/usr/bin/env python3
"""Dedupe candidate postings against state/seen_postings.json.

Usage:
  python3 dedupe.py --input candidates.json --state state/seen_postings.json \
      --config config.json [--output new_only.json]

candidates.json: JSON array of objects with fields:
  company, title, city, highlight, source_url, source_platform
  (discovered_date optional, defaults to today)

Prints the list of newly-seen postings (JSON array) to stdout (or --output
file if given), and updates the state file in place.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

VOLATILE_PARAM_PREFIXES = ("utm_", "spm", "session", "token", "sid", "from", "trace", "_t", "timestamp")


def today_str():
    return date.today().isoformat()


def normalize_text(s):
    if not s:
        return ""
    s = s.strip()
    s = re.sub(r"\s+", "", s)
    s = s.translate(str.maketrans("（）【】", "()[]"))
    return s.lower()


def clean_url(url):
    if not url:
        return ""
    parts = urlsplit(url)
    kept = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not any(k.lower().startswith(p) for p in VOLATILE_PARAM_PREFIXES)
    ]
    kept.sort()
    new_query = urlencode(kept)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), new_query, ""))


def posting_hash(company, title, url):
    key = f"{normalize_text(company)}|{normalize_text(title)}|{clean_url(url)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def fuzzy_key(company, title):
    return f"{normalize_text(company)}|{normalize_text(title)}"


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


def maybe_archive_season(state, config, state_path):
    season_end = config.get("season_end_date")
    if not season_end:
        return state
    try:
        if date.today() <= date.fromisoformat(season_end):
            return state
    except ValueError:
        return state
    season_label = state.get("season", "season")
    archive_path = state_path.replace(".json", f".{season_label}.json")
    save_json(archive_path, state)
    return {"schema_version": 1, "season": season_label, "last_run": None, "postings": {}}


def prune_stale(state, retention_days):
    if not retention_days:
        return state
    cutoff = date.today().toordinal() - int(retention_days)
    kept = {}
    for h, rec in state.get("postings", {}).items():
        try:
            last = date.fromisoformat(rec.get("last_confirmed", rec.get("first_seen", today_str())))
        except ValueError:
            last = date.today()
        if last.toordinal() >= cutoff:
            kept[h] = rec
    state["postings"] = kept
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--output")
    args = ap.parse_args()

    candidates = load_json(args.input, [])
    config = load_json(args.config, {})
    state = load_json(args.state, {"schema_version": 1, "season": config.get("target_season_label", "season"), "last_run": None, "postings": {}})

    state = maybe_archive_season(state, config, args.state)

    postings = state.setdefault("postings", {})
    fuzzy_index = {fuzzy_key(rec["company"], rec["title"]): h for h, rec in postings.items()}

    today = today_str()
    new_only = []

    for c in candidates:
        company = c.get("company", "").strip()
        title = c.get("title", "").strip()
        url = c.get("source_url", "").strip()
        if not company or not title:
            continue

        h = posting_hash(company, title, url)
        fkey = fuzzy_key(company, title)

        if h in postings:
            postings[h]["last_confirmed"] = today
            continue

        if fkey in fuzzy_index:
            existing_h = fuzzy_index[fkey]
            postings[existing_h]["last_confirmed"] = today
            continue

        rec = {
            "company": company,
            "title": title,
            "city": c.get("city", "未注明"),
            "highlight": c.get("highlight", ""),
            "source_platform": c.get("source_platform", ""),
            "source_url": url,
            "first_seen": today,
            "last_confirmed": today,
        }
        postings[h] = rec
        fuzzy_index[fkey] = h
        new_only.append(rec)

    state = prune_stale(state, config.get("state_retention_days"))
    state["last_run"] = datetime.now().astimezone().isoformat()

    save_json(args.state, state)

    out = json.dumps(new_only, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out + "\n")
    else:
        print(out)


if __name__ == "__main__":
    main()