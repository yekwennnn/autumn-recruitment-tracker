---
name: autumn-recruitment-tracker
description: >
  校招求职一体化助手：监控全国新开放的正式校招岗位（目标方向/届别/季节/是否含实习由
  config.json 配置驱动，首次使用先导入简历自动生成配置建议），对每个新岗位抓取JD做
  0-100匹配度深评并写入日报，支持按JD一键定制简历（内嵌 kami 排版与诚实性核查流程，
  STAR法则+实事求是，产出PDF并多版本存档，越用越懂你）。当需要手动触发监控、检查监控
  状态、修改监控方向、查看岗位匹配度、根据JD改简历/定制简历、或管理简历版本时使用此技能。
version: "2.0.0"
user_invocable: true
metadata:
  author: yekaiwen
  version: "2.0.0"
---

# 秋招求职助手：岗位监控 + JD 深评 + 一键改简历

目录约定（不要写死用户名、家目录或安装位置）：

```
SKILL_DIR=.
```

执行本文件中的命令时，以当前这份 `SKILL.md` 所在目录作为工作目录，并使用相对于该目录的路径。所有配置、状态、脚本、简历档案和参考文档都从这里解析，禁止使用发布者机器上的绝对路径或固定技能 ID。

- 配置：`$SKILL_DIR/config.json`（届别/季节/方向/关键词/深评参数/公司池，首次使用可能不存在，见第 0 步）、`$SKILL_DIR/config.example.json`（模板，不要直接改它）
- 状态：`$SKILL_DIR/state/seen_postings.json`（岗位与深评状态，顶层含公众号轮询游标 `wechat_rotation_cursor`）、`$SKILL_DIR/state/match_insights.json`（累积洞察）
- 简历档案：`$SKILL_DIR/resumes/`（`index.json` 版本索引、`profile.json` 求职画像、`originals/` 原件、`versions/<id>/` 各版本）
- 脚本：`$SKILL_DIR/scripts/` 下 `dedupe.py`（去重）、`digest.py`（日报渲染）、`extract_text.py`（PDF/DOCX 文本抽取降级链）、`resume_store.py`（简历档案管理）、`match_state.py`（深评状态机）、`insights.py`（洞察累积）
- 参考文档：`$SKILL_DIR/references/` 下 `sources.md`（6 路数据源与公众号策略）、`keyword-filters.md`（过滤逻辑）、`resume-profile.md`（简历导入与画像）、`matching.md`（JD 抓取契约与评分量表）、`tailoring.md`（一键改简历 W1-W7）、`digest-format.md`（日报格式）
- 内嵌技能：`$SKILL_DIR/vendor/kami/`（简历排版工具箱）、`$SKILL_DIR/vendor/resume-jd-fit/SKILL.md`（JD 定制改简历指引）——一律用读文件方式获取内容，不依赖任何技能加载工具

## 环境能力自检与降级

本技能在能力较弱的 agent 环境下同样可用。开始前对照下表确认可用能力，选择对应路径：

| 依赖点 | 有此能力 | 没有此能力（降级路径） |
|---|---|---|
| 并行子 agent（Agent 工具） | 6 路并行发现；并行抓 JD | 顺序执行精简三路发现（sources.md"弱环境降级"节）；JD 逐条串行抓，单次深评上限自动减半 |
| 提问工具（AskUserQuestion） | 选项式提问 | 纯文字提问；"一键改简历"变为日报尾编号清单，用户回复编号 |
| web-access skill | 子任务 prompt 首句用：「必须加载 web-access skill 并遵循其指引完成联网调研。」 | 改用：「使用你环境中可用的联网工具（网页搜索/网页抓取）完成调研；完全无法联网就如实返回空结果并说明原因。」 |
| 原生读 PDF/图片 | 直接读简历文件 | `python3 $SKILL_DIR/scripts/extract_text.py --file <简历>` |
| Skill 加载工具 | 不需要 | 不需要：vendored 技能一律用读文件方式获取指引 |
| WeasyPrint 等 Python 包 | 产出 PDF 简历 | 交付 HTML + 安装指引（见 README） |

下文所有「{联网句}」占位符，指按本表第三行选择的那句话。

## 入口路由

- **A. 完整监控运行**（默认；定时任务、"跑一次监控"）→ 从第 0 步开始顺序执行。
- **B. 简历工坊**（用户贴 JD、要改简历、问某岗位匹配度、管理/查看简历版本）→ 直接跳到"简历工坊"一节，不跑监控管线。
- **C. 只改设置**（换方向/改关键词/调深评上限/增删公司池）→ 直接改 `$SKILL_DIR/config.json` 对应字段并向用户复述结果。

## 无人值守总则

如果本次运行是定时任务（无人值守）：**不要**使用 AskUserQuestion 或以任何方式等待用户输入；遇到不确定情况一律按本文件和 references 中的默认策略自主处理，并在最终回复里如实说明做了什么假设。（第 0 步的初始化提问例外——见下文。）深评按 config 的 `resume.auto_deep_eval_when_unattended`（默认 true）自动执行；**任何情况下无人值守不得进入简历工坊、不得执行改简历**；无简历档案时跳过第 6 步，日报会自动带提示行。

## 执行步骤

### 0. 首次使用初始化（仅当尚未完成初始化时触发）

读取 `$SKILL_DIR/config.json`；如果这个文件不存在，先把 `$SKILL_DIR/config.example.json` 复制一份成 `$SKILL_DIR/config.json`。

检查 `onboarded` 字段：

- **如果 `onboarded` 不是 `true`，且当前是有用户在场的交互式会话**，依次做：
  - **0.1 导入简历**：请用户提供简历文件（支持 PDF/图片/DOCX/MD/TXT）。拿到后按 `$SKILL_DIR/references/resume-profile.md` 执行：`resume_store.py import-original` 存档原件 → 提取纯文本（环境能直接读就直接读，否则用 `extract_text.py`）→ 生成 `resumes/profile.json` → 建 `resumes/versions/<YYYYMMDD>-base/resume.txt` 并 `register --id <YYYYMMDD>-base --kind base --set-active`。**用户拒绝提供** → 把 config 的 `resume.enabled` 置 `false`，改用 v1 式从零四问（不预填）。
  - **0.2 四问确认（带预填）**：按 resume-profile.md 的推导规则从画像预填 ①目标届别 ②岗位方向 ③是否含实习 ④招聘季节（含 `season_end_date`），请用户确认或纠正——有提问工具就用选项式（预填答案放第一个选项并标"（从简历推断）"），没有就用文字逐条列出确认。确认后由你归纳 `job_filter` 的 `positive_keywords`/`fuzzy_keywords`/`negative_keywords`（`intern_exclusion_keywords`/`formal_recruit_keywords` 用模板默认值即可）。
  - **0.3 生成公司池**：按确认后的方向生成 30-50 家"该方向常开校招"的公司名写入 `discovery.company_watchlist`，展示给用户并说明可随时增删。
  - **0.4 落盘**：把以上全部写进 `$SKILL_DIR/config.json`，置 `onboarded: true`，用一段话向用户复述设置摘要，再继续第 1 步。

- **如果 `onboarded` 不是 `true`，但当前是无人值守的定时任务运行**：不要凭空猜测方向瞎跑一通。直接在最终回复里如实说明"这个技能还没有完成初始化设置，请先手动运行一次、回答几个方向设置问题后再启用定时任务"，然后结束本次运行。

- **如果 `onboarded` 已经是 `true`**：跳过这一步，进入第 1 步。

### 1. 读取配置与档案

读取 `$SKILL_DIR/config.json`。**缺 `resume` 或 `discovery` 块**（老用户升级场景）→ 从 `config.example.json` 把缺的块补进 config.json 再继续。然后：

```
python3 $SKILL_DIR/scripts/resume_store.py status --resumes $SKILL_DIR/resumes
```

- `resume.enabled` 为 true 但档案为空（无 active_base）：**交互式会话** → 按 `references/resume-profile.md`"老用户补传"一节提议补传（走 0.1 再回来）；**无人值守** → 本次跳过第 6 步。
- 档案就绪：读 `resumes/profile.json` 备用；再跑 `python3 $SKILL_DIR/scripts/insights.py show --insights $SKILL_DIR/state/match_insights.json`，输出留给第 6 步和简历工坊当证据。

下文 `{job_category_label}`、`{target_grad_year}`、`{target_season_label}`、`{profile_summary}` 均指代实际值。

### 2. 并行发现（6 路子 agent，公众号一手信息占 3 路）

先读 `$SKILL_DIR/references/sources.md`，按其中 6 路分工，用 Agent 工具在**同一条消息里并行**发起 6 个子任务（general-purpose 类型）：①公众号-新启动公告扫描 ②公众号-公司池轮询（代入本轮 watchlist 批次；完成后把 `wechat_rotation_cursor` 前移 `watchlist_batch_size` 写回 state 顶层）③公众号-新公司挖掘 ④牛客网 ⑤51job校园+智联校园+猎聘校园 ⑥实习僧+其余汇总贴。

每个子 agent 的 prompt 必须：
- 以「{联网句}」开头（按能力自检表选版）。
- 用目标性措辞代入 `{job_category_label}`/`{target_grad_year}`/`{target_season_label}` 实际值，不指定方法动词。
- 追加候选人画像：`{profile_summary}`（不含任何个人身份信息），要求优先关注与画像契合的岗位。
- 要求返回结构化列表，字段：`company`、`title`、`city`（无法判断写"未注明"）、`highlight`（一句话亮点）、`source_url`（完整含参数）、`source_platform`。
- 说明：来源当天不可用就如实报空，不要反复重试。
- **显式禁止子 agent 再自行派发下一层子 agent**（写清楚"必须自己直接完成调研，不得调用 Agent 工具委托其他子 agent"）。
- 给出范围上限："最多深入核实10-15家最相关的公司，覆盖面比逐一核实的精确度更重要"。

等待全部返回；某路为空或失败不影响其余结果，继续往下走。**弱环境（无子 agent 能力）**：按 sources.md"弱环境降级"节顺序执行精简三路。

### 3. 合并 + 过滤

把 6 份结构化列表合并成一个数组。读 `$SKILL_DIR/references/keyword-filters.md` 了解过滤逻辑，按 `config.json` 的 `job_filter` 字段执行：
- 命中 `positive_keywords` 任一 → 保留。
- 命中 `fuzzy_keywords`、但未注明具体方向 → 保留，标题末尾加 `[方向待确认]`。
- 命中 `intern_exclusion_keywords`（含"实习转正"）→ 排除；**但 `include_internships` 为 `true` 时这条整体跳过**。
- 明确写出早于 `target_grad_year` 的届别 → 排除。
- 其余按 keyword-filters.md 处理；地域不过滤，`city` 照抄原文。

把过滤后的候选列表写成 JSON 数组文件 `/tmp/autumn-recruitment-candidates.json`（字段同上）。

### 4. 去重

```
python3 $SKILL_DIR/scripts/dedupe.py \
  --input /tmp/autumn-recruitment-candidates.json \
  --state $SKILL_DIR/state/seen_postings.json \
  --config $SKILL_DIR/config.json \
  --output /tmp/autumn-recruitment-new-only.json
```

这一步会原地更新 state（新岗位写入并携带永久 `id`、已见岗位刷新 `last_confirmed`、过季自动归档），并把真正新增的岗位输出到 `--output` 文件。

### 5. 核实新公司（可选，有上限）

在 `/tmp/autumn-recruitment-new-only.json` 中，找出"公司此前从未出现过"的记录。最多取 5 家这样的新公司，为每家发起一个子 agent（prompt 以「{联网句}」开头，目标是"在该公司官方校园招聘官网核实这个岗位是否存在，若存在返回权威链接"；同样禁止再派子 agent）。核实到官方链接就编辑 new-only 文件和 state 中对应记录的 `source_url`/`source_platform`（`id` 保持不变）；发现届别不符就从两处移除该记录。核实失败或超过 5 家上限的保留原链接。弱环境：跳过本步。

### 6. JD 深评（每个新岗位抓 JD 打匹配分）

`resume.enabled` 为 false、或简历档案为空 → **整步跳过**。规则细节读 `$SKILL_DIR/references/matching.md`。

- 6.1 选待评：`python3 $SKILL_DIR/scripts/match_state.py pending --state $SKILL_DIR/state/seen_postings.json --config $SKILL_DIR/config.json --profile $SKILL_DIR/resumes/profile.json --output /tmp/autumn-recruitment-pending.json`（上限、快评排序、永不重评已在脚本内）。
- 6.2 抓 JD：把 pending 数组按每 5 条一组，最多 `resume.jd_fetch_parallel_agents` 个子 agent 并行，prompt 用 matching.md 的契约模板原文（子 agent 只抓不评分）。**弱环境**：自己逐条串行抓，条数减半。
- 6.3 统一评分：由你（orchestrator）按 matching.md 的五维量表，对照 `profile.json` + 第 1 步的 insights 输出逐条打分，写 `/tmp/autumn-recruitment-evaluated.json`（抓不到的写 `fetched:false` + reason）。证据不足的项按缺失计，禁止脑补。
- 6.4 落库：`python3 $SKILL_DIR/scripts/match_state.py record --state $SKILL_DIR/state/seen_postings.json --config $SKILL_DIR/config.json --input /tmp/autumn-recruitment-evaluated.json`，然后 `python3 $SKILL_DIR/scripts/insights.py ingest-eval --insights $SKILL_DIR/state/match_insights.json --input /tmp/autumn-recruitment-evaluated.json`。

### 7. 渲染日报

```
python3 $SKILL_DIR/scripts/digest.py render \
  --new /tmp/autumn-recruitment-new-only.json \
  --state $SKILL_DIR/state/seen_postings.json \
  --config $SKILL_DIR/config.json \
  --evaluated /tmp/autumn-recruitment-evaluated.json \
  --resumes $SKILL_DIR/resumes \
  --date $(date +%F) > /tmp/autumn-recruitment-digest.md
```

（第 6 步被跳过时省略 `--evaluated`。）

### 8. 输出与一键入口

最终回复内容 = `/tmp/autumn-recruitment-digest.md` 的完整内容，原样输出，不需要额外包装。无论有没有新增岗位都必须输出日报，不要空手结束任务。

输出日报后，**仅交互式会话**再做一步：取本次 `score >= resume.min_score_for_action` 的岗位——
- 有提问工具：选项式提问（最多 4 个岗位选项 + "先不改"），用户选中即携带该岗位进入简历工坊 W1。这就是"一键改简历"。
- 无提问工具：在日报尾追加编号岗位清单和一句"回复编号即可为该岗位定制简历"。

**无人值守：输出日报即结束。**

## 简历工坊

三个子入口（无人值守一律不进入本节）：

- **定制简历**（一键选中的岗位，或用户贴 JD/说"帮我改简历投XX"）：完整执行 `$SKILL_DIR/references/tailoring.md` 的 W1-W7——选基底、诚实性核查（先查 insights 已沉淀素材，不重复问；新答案立刻 add-fact）、STAR + 实事求是改写、kami 渲染（缺 WeasyPrint 降级 HTML）、四件套存档注册、交付改动清单与前后分数。**诚实性核查（W3）和 STAR 实事求是（W4）在任何环境都不可跳过；每次产出必须 register 存档。**
- **单个 JD 现评**（用户贴 JD 问匹配度）：按 `references/matching.md` 量表现场打分并给一句优势/一句差距，不写入 state；用户接着要改简历就把分数当 `score_before` 转入定制流程。
- **查看档案**：`python3 $SKILL_DIR/scripts/resume_store.py list --resumes $SKILL_DIR/resumes`，需要细节时展示对应版本目录下的 `meta.json`。
