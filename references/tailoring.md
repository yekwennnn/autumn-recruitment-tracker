# 一键改简历（简历工坊 W1-W7）

本流程把三样东西串起来：`vendor/resume-jd-fit/SKILL.md`（六步定制法，直接 Read 当操作指引）、`vendor/kami/`（排版工具箱）、本仓库的档案与洞察脚本。**无人值守（定时任务）绝对禁止进入本流程**——诚实性核查必须有用户在场应答。

## 入口

- (a) 监控日报输出后，用户选中某个高分岗位（选项按钮或回复编号）。
- (b) 用户任何时候贴 JD / 说"帮我改简历投XX"（走 SKILL.md 入口路由 B，不跑监控管线）。

## W1 取材

- 来自日报的岗位：直接用 state 里该岗位的 `match.jd_summary` / `jd_url`；需要更多细节时按 `references/matching.md` 的抓取契约现抓全文。
- 用户贴的 JD：直接用原文。

## W2 选基底

```
python3 $SKILL_DIR/scripts/resume_store.py pick-base --resumes $SKILL_DIR/resumes \
  --keywords "<jd_keywords 逗号串>"
```

向用户确认选中的基底版本后定稿。`score_before` = 该基底对本 JD 的匹配分：岗位在 state 里已有 `match.score` 就直接用；否则按 matching.md 量表现打一次。

## W3 差距分析与诚实性核查

1. 先跑 `python3 $SKILL_DIR/scripts/insights.py show --insights $SKILL_DIR/state/match_insights.json`——**`confirmed_facts` 里已沉淀的素材不要重复追问用户**，直接当作已核实证据用。
2. 然后执行 `vendor/resume-jd-fit/SKILL.md` 的 **Step 1（JD 差距分析）→ Step 2（诚实性核查）→ Step 3（保密脱敏）**，一步不跳。
3. Step 2 每问出一条新的真实素材，**立刻**沉淀：

```
python3 $SKILL_DIR/scripts/insights.py add-fact --insights $SKILL_DIR/state/match_insights.json \
  --claim "<一句话主张>" --detail "<具体做了什么/角色/产出>" --stage "demo|个人使用|已上线|其他"
```

## W4 改写

执行 resume-jd-fit 的 **Step 4**（复用现有简历结构原地改内容）。基底没有 HTML（例如初始导入的是 PDF）→ 按 `vendor/kami/assets/templates/resume.html` 起版，动笔前先读 `vendor/kami/CHEATSHEET.md` + `vendor/kami/references/resume-writing.md`；**声明跳过** kami SKILL.md 的 Step 0（品牌档案）与 diagrams 路由（相关文件未内嵌）。

> **STAR + 实事求是（每条 bullet 逐条过，不许跳）**
> - 每条经历/项目按 STAR 组织：Situation+Task 压成一句背景（什么场景要解决什么问题）；Action 突出**本人**动作并与 JD 关键词自然对齐；Result 单独写真实结果。与 kami `resume-writing.md` 的 Role/Action/Result 标准兼容（Role≈S/T），冲突时以 STAR 为准。
> - 三条红线：① Result 没有真实数字就写规模/状态（如"个人使用，未对外发布"），**禁止编造任何指标**；② 工具辅助查资料 ≠ 开发经验、demo ≠ 上线产品，措辞严格按 resume-jd-fit Step 2 的对照表；③ JD 要求而简历无证据的能力，宁可留白说明，不许硬凑（与 matching.md"无证据按缺失计"同一原则）。
> - 每条改动记入 meta.json 的 `changes[]`，交付时逐条向用户报告依据，保证每句话面试都能答上。

## W5 渲染

1. `bash $SKILL_DIR/vendor/kami/scripts/ensure-fonts.sh` —— 失败**不阻断**（模板自带 CDN 与系统字体兜底链）。
2. 渲染 PDF：

```
python3 -c "from weasyprint import HTML; HTML('<版本目录>/source.html', base_url='<版本目录>').write_pdf('<版本目录>/resume.pdf')"
```

3. 用 pypdf 数页数；超过一页 → 按 resume-jd-fit **Step 5** 修（装了 pdfplumber 就量化测缺口再改；没装就按"压 dense 字号 → 削页边距 → 合并内容行"顺序改后重测页数）。同时按其 Bug 2 检查所有 CJK 标签列不换行。

**降级阶梯**：
- 无 WeasyPrint → 只交付 `source.html`（meta.json 的 `render` 记 `html_only`），附一句安装指引（见 README"想直接出 PDF 简历？"节）。
- 无 pymupdf → 不做旧 PDF 抽照片，改为请用户提供照片文件，或不放照片。

## W6 存档

版本命名：基底 `YYYYMMDD-base`；定制版 `YYYYMMDD-<公司slug>-<岗位slug>`（中文 slug = 原文去空格截 8 字；英文 = 小写连字符）；同日同岗第二版加 `-v2`。

`mkdir -p $SKILL_DIR/resumes/versions/<版本id>/`，写**四件套**：

| 文件 | 内容 |
|---|---|
| `source.html` | 终稿 kami HTML |
| `resume.pdf` | 渲染成功才有 |
| `resume.txt` | 终稿纯文本（供未来 pick-base 全文检索） |
| `meta.json` | schema 见下 |

```json
{
  "id": "20260801-tencent-fengkong",
  "base_version": "20260724-base",
  "created_at": "2026-08-01T15:00:00+08:00",
  "target": { "company": "腾讯", "title": "金融科技风控岗", "jd_url": "https://...", "posting_id": "<sha1或null>" },
  "jd_summary": "...",
  "changes": [ "把审计项目重排到首位", "新增扣子工作流项目（已核实：demo阶段）" ],
  "score_before": 68,
  "score_after": 84,
  "honesty_checked": true,
  "render": "pdf | html_only"
}
```

`score_after` = 改后简历对**同一 JD** 按量表重打。然后注册 + 记战绩：

```
python3 $SKILL_DIR/scripts/resume_store.py register --resumes $SKILL_DIR/resumes \
  --id <版本id> --kind tailored --label "<公司>-<岗位>定制版" \
  --txt versions/<版本id>/resume.txt --html versions/<版本id>/source.html \
  [--pdf versions/<版本id>/resume.pdf] \
  --company <公司> --title <岗位> [--posting-id <sha1>] --jd-url <URL> \
  --base <基底id> --score-before <X> --score-after <Y> --tags "<jd_keywords 前几个>"
python3 $SKILL_DIR/scripts/insights.py log-version --insights $SKILL_DIR/state/match_insights.json \
  --version <版本id> --tags "<同上>" --score <Y> --target "<公司>-<岗位>"
```

（定制版**不** `--set-active`——active_base 是总简历，见 resume-profile.md。）

## W7 交付

按 resume-jd-fit **Step 6** 清单自检后交付，必须向用户列出：
- 改动清单（`changes[]`）及每条的依据——尤其 demo 级项目和 AI 相关素材的措辞出处；
- 改前/改后匹配分（score_before → score_after）；
- 存档位置（`resumes/versions/<版本id>/`）与产物形态（PDF 或 HTML）。
