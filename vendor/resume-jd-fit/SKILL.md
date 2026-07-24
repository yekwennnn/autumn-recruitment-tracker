---
name: resume-jd-fit
description: 'Use whenever the user wants to tailor an existing resume to a specific job posting/JD — phrases like "根据这个JD改简历", "投这个岗位帮我调整简历", "针对这个职位优化一下我的简历", or "tailor my resume for this role". Also trigger if the user pastes a job description alongside a resume file, or asks to "make my resume fit this posting" without explicit "JD" wording. This skill enforces an honesty pass on any AI/tech-capability claims before writing, redacts confidential employer/client data, reuses the existing kami-built resume (including any embedded headshot) as the base, and fixes the two recurring kami one-pager failure modes: page overflow and CJK label wrapping. Do not just rewrite bullets to match keywords — run the honesty and confidentiality checks first, every time.'
---

# Resume ⇄ JD Fit

> 内嵌副本（vendored copy）：本文件随 autumn-recruitment-tracker 分发，供其"简历工坊"流程作为操作指引直接 Read 使用；入口、路径与降级适配见仓库 `references/tailoring.md`。文中 `kami` 一律指本仓库 `vendor/kami/` 内嵌子集。

Tailor an existing resume to a specific job posting without fabricating experience, leaking confidential employer/client data, or breaking the one-page kami layout.

This skill assumes the resume is (or will be) built with the vendored kami toolkit at `vendor/kami/` (template: `assets/templates/resume.html`; guidance: `vendor/kami/SKILL.md` and `vendor/kami/references/resume-writing.md`). If no resume exists yet, build one from that template first, then come back here for JD-fitting.

## Step 0 · Gather inputs

Need: (1) the JD text, (2) the current resume (file or prior kami source), (3) any raw material the user mentions in passing ("我用AI做了个XX", "审计里我还做了YY") that isn't already on the resume.

If the user only pastes a JD with no resume, ask for the resume before doing anything else — don't guess at their background.

## Step 1 · JD gap analysis (silent, then surface only the gaps)

Read the JD and split requirements into:
- **Hard requirements** the resume already evidences
- **Hard requirements** the resume doesn't evidence at all — don't invent content to cover these; either find real material via Step 2, or leave them uncovered and say so
- **Nice-to-haves** that can shift emphasis/wording without adding new claims

Do not start writing bullets yet. Go to Step 2 first if the user has mentioned *any* new experience (AI tools, side projects, informal work) that isn't already fully specified on the resume.

## Step 2 · Honesty pass on new/vague claims (mandatory before writing)

This is the step that's easiest to skip and most likely to produce a resume the candidate can't defend in an interview. Run it every time the user mentions using AI, building something, or doing anything not already precisely described.

For each new claim, ask (compact, one message, batch the questions):
1. **What exactly did you build/do?** — get the concrete artifact (script, workflow, agent) not the category ("AI辅助" is not an answer; "调用QQ音乐接口写的本地播放脚本" is).
2. **What was your role vs. the tool's role?** — did you write the requirements and the AI generated code (you debugged), or did you write the logic yourself and just use AI for lookup/summarization? These get very different framings.
3. **What stage is it at?** — demo/personal use only, or shipped and used by others? Never let a demo get written as "developed and deployed."

Framing rules once you have real answers:
- No number → state magnitude/scope instead ("demo, no real users", "个人使用，未对外发布"), never invent a metric.
- Tool-assisted lookup/summarization ≠ development experience. Label it as an efficiency tool in the skills section, not as a project.
- Genuine "wrote requirements → AI generated code → I debugged" IS legitimate AI-dev experience — write it as its own project entry, honestly scoped (see the framing table below).

| What actually happened | How to write it |
|---|---|
| Used ChatGPT/Claude to search/summarize for a task | One clause under existing skill row, e.g. "日常借助 X 工具辅助资料检索" — not a project |
| Used Coze/扣子 or similar to build an actual workflow/agent | A real project entry, name the workflow and its trigger/output |
| Wrote requirements, AI wrote code, user debugged it, demo stage | A project entry, explicitly tagged demo/个人技术探索/非产品级 in the role tag, three-part Role/Action/Result, result = "跑通一次完整流程" not a fabricated user/scale number |
| Anything the user is unsure how to characterize | Ask, don't guess toward the more impressive interpretation |

## Step 3 · Confidentiality redaction

Flag anything that touches a former employer's or client's non-public data before it goes on the resume — this comes up constantly in audit/consulting/finance resumes ("我核对了客户的银行流水/合同/薪资数据" etc).

Rule: describe the **method or skill demonstrated**, never the specific data, account, or client-identifying detail. If in doubt, ask the user "结果里能不能不提具体是哪家客户/哪类账户" rather than deciding silently — but default to the safe rewrite and flag it, don't ship the risky version to check.

Good: "在银行流水与账面记录的核对环节，借助 AI 工具辅助梳理核对规则、归纳异常线索"
Bad: any phrasing that names the client, discloses account-level specifics, or implies the AI tool touched the raw confidential data itself.

## Step 4 · Reuse the existing resume, don't rebuild from scratch

- Copy the user's current kami-built HTML/PDF structure (header, metrics, section order, CSS) and edit content in place. Don't restyle or restructure unless asked.
- **Reuse an existing headshot.** If the user has a prior resume PDF with an embedded photo and now wants a photo added, extract it instead of asking them to re-upload:
  ```python
  import fitz  # pymupdf
  doc = fitz.open("path/to/old_resume.pdf")
  for img in doc[0].get_images(full=True):
      pix = fitz.Pixmap(doc, img[0])
      pix.save("headshot.png")
  ```
  Place it as a small rounded-square (~17–20mm) beside the name, `object-fit: cover`, `object-position: top center`. Tell the user which file it came from — don't silently assume they're happy with an old photo, but don't block on it either; proceed and mention it.
- Reposition the target-role tagline (the small colored line near the name/contact) to match the new JD's title/domain, but keep it honest — a positioning line, not a claimed title.

## Step 5 · Fit to one page (the two recurring kami bugs)

### Bug 1: page overflow after edits

Adding even one project or a photo routinely pushes a tight one-pager to two pages. Fix with measurement, not guesswork:

1. Build with WeasyPrint, check page count with `pypdf`.
2. If >1 page: **temporarily strip any `.no-break` class from the last section** before measuring — `break-inside: avoid` will shove an entire section to page 2 even if it's only short by a few points, which hides the true overflow size.
3. Measure the actual gap with `pdfplumber`: compare the last word's `bottom` on page 1 against `page.height` minus the bottom margin, and the leftover content's height on page 2. This tells you exactly how many points/mm you need to reclaim — don't cut content by feel.
4. Reclaim space in this order, smallest change first:
   - Tighten `resume--dense` overrides (font-size ~8.7–9pt, `.proj-text`/`.skill-body` line-height ~1.32–1.38, section-title margins ~2.5–3mm)
   - Shave `@page` margin by 1mm increments (down to ~6mm before it looks cramped)
   - Only then cut/merge actual content rows (merge Role+Action before cutting Result — Result is the highest-value row)
5. Once it's exactly one page, restore the `.no-break` class on the last section so future small edits don't silently split it again.
6. Re-verify page count after restoring `.no-break`.

### Bug 2: CJK label wrapping

Any label column (`.proj-label`, `.skill-label`, or similar fixed-width cell) can wrap a 4-character Chinese label onto two lines if the column is too narrow. Rule of thumb: at 9pt, one CJK character ≈ 9pt wide, so a 4-character label needs ≈36pt (≈12.7mm) of column width minimum — the stock kami template's `.proj-label` default (11mm) is too narrow for 4-character labels and will wrap.

Fix: widen the column to ≥14mm, set `letter-spacing: 0`, and add `white-space: nowrap` on the label cell. Check every label column in the document, not just the one the user flagged — if one wrapped, others at the same width are likely to also wrap or be one edit away from it.

## Step 6 · Final check before delivering

- Every new/reworded claim traces back to something the user actually confirmed in Step 2 — no silent upgrades.
- No confidential specifics leaked (Step 3).
- Page count is 1 (or whatever the user's target length is) after restoring `.no-break`.
- No label wrapping anywhere in the document.
- Photo (if added) is reused from existing material, not fabricated or left as a generic placeholder.

Deliver the PDF and name the specific edits made, so the user can sanity-check anything they'd need to defend in an interview — especially demo-stage projects and reframed AI claims.
