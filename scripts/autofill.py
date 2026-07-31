#!/usr/bin/env python3
"""Safe browser form filler for job-copilot.

This is deliberately a fill-and-review tool.  It talks to the Web Access CDP
Proxy, never calls click on submit, and persists only a redacted form manifest.
The browser must already be authorized by the user; this script does not log
in, install extensions, bypass challenges, or submit applications.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

try:
    from db import redact
except ImportError:
    from .db import redact


PROXY = "http://localhost:3456"
RISK_NOTICE = "温馨提示：部分站点对浏览器自动化操作检测严格，存在账号封禁风险。已内置防护措施但无法完全避免，Agent 继续操作即视为接受。"

SAFE_FIELD_PATTERNS = {
    "name": ("姓名", "name", "realname", "full name"),
    "email": ("邮箱", "email", "e-mail", "mail"),
    "phone": ("手机", "电话", "手机号", "mobile", "phone", "tel"),
    "city": ("城市", "所在地", "current city", "location"),
    "school": ("学校", "院校", "school", "university", "college"),
    "major": ("专业", "major", "field of study"),
    "degree": ("学历", "学位", "degree", "education level"),
    "graduation": ("毕业时间", "毕业年份", "graduation", "graduated"),
    "education": ("教育经历", "教育背景", "education history", "education experience"),
    "work": ("工作经历", "工作经验", "work experience", "employment history", "experience"),
    "project": ("项目经历", "项目经验", "project experience", "projects"),
    "skills": ("技能", "专业技能", "skills", "technical skills", "technology"),
    "arrival": ("到岗", "可入职", "available", "start date", "availability"),
    "website": ("个人主页", "作品集", "github", "portfolio", "website"),
}

SENSITIVE_PATTERNS = (
    "密码", "password", "passwd", "验证码", "captcha", "短信", "sms", "身份证", "id number",
    "银行卡", "bank", "健康", "残疾", "犯罪", "征信", "background check", "signature", "签名",
    "真实性", "承诺", "同意", "consent", "salary", "薪资", "期望薪资",
)


def http(method: str, path: str, body=None):
    url = PROXY + path
    data = None
    headers = {}
    if body is not None:
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else str(body)).encode("utf-8")
        headers["Content-Type"] = "application/json" if isinstance(body, (dict, list)) else "text/plain;charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Web Access CDP Proxy 不可用：{exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def target_id_from(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("targetId", "target", "id"):
            if value.get(key):
                return value[key]
    raise RuntimeError(f"CDP Proxy 没有返回 target id：{value}")


def new_target(url):
    return target_id_from(http("GET", "/new?url=" + urllib.parse.quote(url, safe="")))


def eval_js(target, expression):
    value = http("POST", "/eval?target=" + urllib.parse.quote(str(target), safe=""), expression)
    if isinstance(value, dict) and value.get("error"):
        raise RuntimeError(f"页面脚本执行失败：{value['error']}")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def inspect_controls(target):
    expression = r'''(() => Array.from(document.querySelectorAll('input,textarea,select')).map((el, index) => {
      el.setAttribute('data-job-copilot-control', String(index));
      const label = el.labels && el.labels[0] ? el.labels[0].innerText : '';
      const parent = el.closest('label');
      const nearby = parent ? parent.innerText : '';
      return {
        index,
        name: el.name || '',
        id: el.id || '',
        type: el.type || el.tagName.toLowerCase(),
        placeholder: el.placeholder || '',
        aria: el.getAttribute('aria-label') || '',
        label: label || nearby,
        required: Boolean(el.required),
        value: el.value || '',
        options: el.tagName.toLowerCase() === 'select' ? Array.from(el.options).map(o => ({value:o.value,text:o.text})) : []
      };
    }))()'''
    controls = eval_js(target, expression)
    if not isinstance(controls, list):
        raise RuntimeError("无法读取页面表单控件")
    for control in controls:
        control["haystack"] = " ".join(str(control.get(k, "")) for k in ("name", "id", "placeholder", "aria", "label")).lower()
    return controls


def is_sensitive(control):
    haystack = control.get("haystack", "")
    return any(pattern.lower() in haystack for pattern in SENSITIVE_PATTERNS)


def field_match(control, patterns):
    haystack = control.get("haystack", "")
    return any(pattern.lower() in haystack for pattern in patterns)


def fill_control(target, control, value):
    index = int(control["index"])
    js_value = json.dumps(str(value), ensure_ascii=False)
    expression = f'''(() => {{
      const el = document.querySelector('[data-job-copilot-control="{index}"]');
      if (!el) return {{ok:false, reason:'not-found'}};
      const value = {js_value};
      if (el.tagName.toLowerCase() === 'select') {{
        const option = Array.from(el.options).find(o => o.value === value || o.text.trim() === value);
        if (!option) return {{ok:false, reason:'option-not-found'}};
        el.value = option.value;
      }} else if (!['checkbox','radio','file','password'].includes((el.type || '').toLowerCase())) {{
        el.value = value;
      }} else return {{ok:false, reason:'unsafe-type'}};
      el.dispatchEvent(new Event('input', {{bubbles:true}}));
      el.dispatchEvent(new Event('change', {{bubbles:true}}));
      return {{ok:true}};
    }})()'''
    result = eval_js(target, expression)
    return bool(isinstance(result, dict) and result.get("ok"))


def set_files(target, control, file_paths):
    index = int(control["index"])
    selector = f'[data-job-copilot-control="{index}"]'
    http("POST", "/setFiles?target=" + urllib.parse.quote(str(target), safe=""), {"selector": selector, "files": [str(Path(path).expanduser().resolve()) for path in file_paths]})


def uploaded_file_names(target):
    expression = r'''(() => Array.from(document.querySelectorAll('input[type=file]')).flatMap(el => Array.from(el.files || []).map(file => file.name)))()'''
    result = eval_js(target, expression)
    return result if isinstance(result, list) else []


def invalid_controls(target):
    expression = r'''(() => Array.from(document.querySelectorAll('input,textarea,select')).filter(el => !el.checkValidity()).map(el => ({
      index: el.getAttribute('data-job-copilot-control'), name: el.name || '', id: el.id || '',
      type: el.type || el.tagName.toLowerCase(), placeholder: el.placeholder || '',
      aria: el.getAttribute('aria-label') || '', label: el.labels && el.labels[0] ? el.labels[0].innerText : '',
      required: Boolean(el.required), value: el.value || ''
    })))()'''
    result = eval_js(target, expression)
    return result if isinstance(result, list) else []


def profile_values(path: str) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("profile JSON 必须是对象")
    values = raw.get("application_profile") if isinstance(raw.get("application_profile"), dict) else raw
    aliases = {
        "name": ("name", "姓名", "full_name"),
        "email": ("email", "邮箱"),
        "phone": ("phone", "电话", "mobile"),
        "city": ("city", "城市", "location"),
        "school": ("school", "学校", "university"),
        "major": ("major", "专业"),
        "degree": ("degree", "学历", "education"),
        "graduation": ("graduation", "毕业年份", "graduation_year"),
        "education": ("education", "教育经历", "education_history"),
        "work": ("work", "工作经历", "work_experience", "employment"),
        "project": ("project", "项目经历", "project_experience"),
        "skills": ("skills", "技能", "technical_skills"),
        "arrival": ("arrival", "到岗日期", "available_date", "start_date"),
        "website": ("website", "portfolio", "github"),
    }
    result = {}
    for field, keys in aliases.items():
        for key in keys:
            if values.get(key) not in (None, ""):
                result[field] = str(values[key])
                break
    return result


def jobctl(args, extra):
    script = Path(__file__).with_name("jobctl.py")
    command = [sys.executable, str(script)]
    if args.data_dir:
        command += ["--data-dir", args.data_dir]
    command += extra
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip()


def inspect(args):
    print(RISK_NOTICE)
    target = new_target(args.url)
    controls = inspect_controls(target)
    safe_controls = []
    for control in controls:
        redacted = dict(control)
        redacted["value"] = redact(redacted.get("value", ""))
        safe_controls.append(redacted)
    print(json.dumps({"target": target, "controls": safe_controls}, ensure_ascii=False, indent=2))
    if not args.keep:
        http("GET", "/close?target=" + urllib.parse.quote(str(target), safe=""))


def fill(args):
    if not Path(args.profile_json).exists():
        raise RuntimeError(f"找不到 profile JSON：{args.profile_json}")
    values = profile_values(args.profile_json)
    print(RISK_NOTICE)
    session = jobctl(args, ["form", "start", "--posting-id", args.posting_id, "--resume-version-id", args.resume_version_id, "--form-url", args.url, "--json"])
    session_id = session["form_session_id"]
    target = new_target(args.url)
    blocked = []
    try:
        controls = inspect_controls(target)
        for field, value in values.items():
            candidates = [control for control in controls if control.get("type") not in {"file", "hidden", "password", "checkbox", "radio"} and field_match(control, SAFE_FIELD_PATTERNS[field])]
            if not candidates:
                continue
            candidate = candidates[0]
            if is_sensitive(candidate) or not fill_control(target, candidate, value):
                blocked.append({"field": field, "reason": "sensitive_or_fill_failed"})

        files = [control for control in controls if control.get("type") == "file"]
        expected_uploads = []
        if args.resume_file and files:
            set_files(target, files[0], [args.resume_file])
            expected_uploads.append(Path(args.resume_file).name)
        if args.photo_file and len(files) > 1:
            set_files(target, files[1], [args.photo_file])
            expected_uploads.append(Path(args.photo_file).name)
        if expected_uploads:
            observed_uploads = uploaded_file_names(target)
            for filename in expected_uploads:
                if filename not in observed_uploads:
                    blocked.append({"field": filename, "reason": "upload_filename_not_observed"})

        invalid = invalid_controls(target)
        for control in invalid:
            haystack = " ".join(str(control.get(k, "")) for k in ("name", "id", "placeholder", "aria", "label")).lower()
            if control.get("required") or is_sensitive({"haystack": haystack}):
                blocked.append({"field": control.get("name") or control.get("id") or control.get("label") or f"control-{control.get('index')}", "reason": "required_or_sensitive"})
        manifest = {key: redact(value) for key, value in values.items()}
        manifest["resume_file"] = Path(args.resume_file).name if args.resume_file else None
        manifest["photo_file"] = Path(args.photo_file).name if args.photo_file else None
        manifest["submit_button"] = "intentionally_not_clicked"
        unique_blocked = []
        seen = set()
        for item in blocked:
            marker = (item.get("field"), item.get("reason"))
            if marker not in seen:
                seen.add(marker); unique_blocked.append(item)
        status = "blocked" if unique_blocked else "ready_for_review"
        jobctl(args, ["form", "update", session_id, "--status", status, "--manifest-json", json.dumps(manifest, ensure_ascii=False), "--blocked-fields-json", json.dumps(unique_blocked, ensure_ascii=False), "--json"])
        print(json.dumps({"form_session_id": session_id, "target": target, "status": status, "blocked_fields": unique_blocked, "submitted": False}, ensure_ascii=False, indent=2))
    except Exception as exc:
        try:
            jobctl(args, ["form", "update", session_id, "--status", "blocked", "--blocked-fields-json", json.dumps([{"field": "browser", "reason": redact(str(exc))}], ensure_ascii=False), "--json"])
        finally:
            print(json.dumps({
                "form_session_id": session_id,
                "status": "blocked",
                "manual_fields": sorted(values),
                "message": "浏览器自动化未完成，请人工填写并保持在最终提交前；未点击提交。",
                "submitted": False,
            }, ensure_ascii=False, indent=2))
            raise


def main(argv=None):
    ap = argparse.ArgumentParser(description="安全网申填写：只填写和保存草稿，不提交")
    ap.add_argument("--data-dir")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect"); p.add_argument("--url", required=True); p.add_argument("--keep", action="store_true"); p.set_defaults(func=inspect)
    p = sub.add_parser("fill"); p.add_argument("--url", required=True); p.add_argument("--posting-id", required=True); p.add_argument("--resume-version-id", required=True); p.add_argument("--profile-json", required=True); p.add_argument("--resume-file"); p.add_argument("--photo-file"); p.set_defaults(func=fill)
    args = ap.parse_args(argv)
    try:
        args.func(args)
    except RuntimeError as exc:
        print(f"错误：{redact(exc)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
