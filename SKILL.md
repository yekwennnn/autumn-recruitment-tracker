---
name: autumn-recruitment-tracker
description: >
  校招求职一体化助手：先读简历、给出简历分析与岗位方向推荐，再按确认的方向监控全国新开放的
  正式校招岗位（届别/季节/是否含实习由 config.json 驱动）。发现层按"公众号每天、聚合平台
  每周"轮转并用便宜模型跑，对每个新岗位抓 JD 做 0-100 匹配度深评、抓网申截止日期并预警，
  支持按 JD 一键定制简历（内嵌 kami 排版与诚实性核查，STAR法则+实事求是，产出PDF并多版本
  存档），还能自动填写企业官网的网申表单（北森/zhiye 等校招网申系统：个人信息档案化、逐字段
  核对、提交前必须经你确认），投出去之后还能追踪进展。当需要首次设置、手动触发监控、检查监控
  状态、修改监控方向、查看岗位匹配度、根据JD改简历、管理简历版本、记录/查询投递进展、或者要
  帮忙填网申/自动填写某公司官网网申表单时使用此技能。
version: "2.1.0"
user_invocable: true
metadata:
  author: yekaiwen
  version: "2.1.0"
---

# 秋招求职助手：简历分析 + 岗位监控 + JD 深评 + 改简历 + 投递追踪

目录约定（不要写死用户名、家目录或安装位置）：

```
SKILL_DIR=.
TMP=$SKILL_DIR/state/tmp
```

执行本文件中的命令时，以当前这份 `SKILL.md` 所在目录作为工作目录，并使用相对于该目录的路径。所有配置、状态、脚本、简历档案和参考文档都从这里解析，禁止使用发布者机器上的绝对路径或固定技能 ID。中间文件一律写 `$TMP`，**不要用 `/tmp`**——多个运行会互相覆盖，残留文件还会串进下一次日报。

- 配置：`$SKILL_DIR/config.json`（届别/季节/方向/关键词/深评参数/公司池/发现层策略，首次使用可能不存在，见第 0 步）、`$SKILL_DIR/config.example.json`（模板，不要直接改它）
- 状态：`$SKILL_DIR/state/seen_postings.json`（岗位、深评状态、截止日期，顶层含发现层账本）、`$SKILL_DIR/state/match_insights.json`（累积洞察）、`$SKILL_DIR/state/applications.json`（投递记录）
- 简历档案：`$SKILL_DIR/resumes/`（`index.json` 版本索引、`profile.json` 求职画像与简历分析、`originals/` 原件、`versions/<id>/` 各版本、`webapply-profile.json` 网申档案（含真实联系方式与开放题答案库，绝不入库）、`photos/` 证件照）
- 脚本：`$SKILL_DIR/scripts/` 下 `discovery.py`（发现层排程与账本）、`dedupe.py`（去重）、`digest.py`（日报渲染）、`extract_text.py`（PDF/DOCX 文本抽取降级链）、`resume_store.py`（简历档案管理）、`match_state.py`（深评状态机）、`insights.py`（洞察累积）、`apply.py`（投递追踪）、`make_campus_template.py`（生成校招简历模板）
- 简历模板：`$SKILL_DIR/assets/templates/resume-campus-cn.html`（**中文校招默认模板**，一页制，教育背景在实习经历之前；由 `make_campus_template.py` 从 `assets/campus-body.html` + kami 版式生成，**不要直接编辑**）
- 参考文档：`$SKILL_DIR/references/` 下 `sources.md`（车道定义与轮转策略）、`keyword-filters.md`（过滤逻辑）、`resume-profile.md`（简历导入、分析与画像）、`matching.md`（JD 抓取契约与评分量表）、`tailoring.md`（一键改简历 W1-W7）、`applications.md`（投递追踪）、`webapply.md`（网申自动填表）、`webapply-patterns/<domain>.md`（各网申系统的表单经验，只存结构不存个人数据）、`digest-format.md`（日报格式）
- 内嵌技能：`$SKILL_DIR/vendor/kami/`（简历排版工具箱）、`$SKILL_DIR/vendor/resume-jd-fit/SKILL.md`（JD 定制改简历指引）——一律用读文件方式获取内容，不依赖任何技能加载工具
- 外部依赖（**仅网申填表用**）：`web-access` skill 提供浏览器 CDP 能力——优先用技能加载工具加载，加载不了就读 `~/.claude/skills/web-access/SKILL.md`。本技能只调用它的 `scripts/check-deps.mjs`、`scripts/cdp-proxy.mjs` 和 `localhost:3456` 的 HTTP 接口；**网申表单经验写在本技能自己的 `references/webapply-patterns/`**，不写进 web-access 的目录（纯浏览层的通用经验除外，那个按它自己的约定写它的 `site-patterns/`）

## 环境能力自检与降级

本技能在能力较弱的 agent 环境下同样可用。开始前对照下表确认可用能力，选择对应路径：

| 依赖点 | 有此能力 | 没有此能力（降级路径） |
|---|---|---|
| 并行子 agent（Agent 工具） | 按 plan 并行发现；并行抓 JD | 顺序执行 plan 里的车道（sources.md"弱环境降级"节）；JD 逐条串行抓，单次深评上限自动减半 |
| 子 agent 可指定模型 | 按 plan 的 `model` 字段发起，发现层走便宜模型 | 忽略 `model` 字段照常发起，其余机制不变（只是更贵） |
| 提问工具（AskUserQuestion） | 选项式提问 | 纯文字提问；"一键改简历"变为日报尾编号清单，用户回复编号 |
| web-access skill | 子任务 prompt 首句用：「必须加载 web-access skill 并遵循其指引完成联网调研。」 | 改用：「使用你环境中可用的联网工具（网页搜索/网页抓取）完成调研；完全无法联网就如实返回空结果并说明原因。」 |
| 浏览器 CDP（web-access 的 cdp-proxy，**仅网申填表用**） | 按 `references/webapply.md` 全流程自动填表 | 不做任何浏览器操作：档案初始化照常，改为产出「字段-答案清单」给用户复制粘贴手填（webapply.md 第 8 节）。档案与开放题答案库照常沉淀，不白干 |
| 原生读 PDF/图片 | 直接读简历文件 | `python3 $SKILL_DIR/scripts/extract_text.py --file <简历>` |
| Skill 加载工具 | 不需要 | 不需要：vendored 技能一律用读文件方式获取指引 |
| WeasyPrint / pypdf | 产出 PDF 简历、数页数 | 交付 HTML + 安装指引（见 README）；`--check-placeholders` 不依赖它们，照跑 |

下文所有「{联网句}」占位符，指按本表 **web-access skill** 那一行选择的那句话。

## 入口路由

- **A. 完整监控运行**（默认；定时任务、"跑一次监控"）→ 从第 0 步开始顺序执行。
- **B. 简历工坊**（用户贴 JD、要改简历、问某岗位匹配度、管理/查看简历版本、想重看简历分析）→ 直接跳到"简历工坊"一节，不跑监控管线。
- **C. 只改设置**（换方向/改关键词/调深评上限/增删公司池/启停某条发现车道）→ 直接改 `$SKILL_DIR/config.json` 对应字段并向用户复述结果。
- **D. 投递追踪**（"我投了XX""XX让我去面试了""我投了哪些""哪一版简历过筛率高"）→ 直接跳到"投递追踪"一节。
- **E. 网申填表**（"帮我填XX的网申""自动填一下网申""投一下XX官网"，通常带网申链接或公司名）→ 直接跳到"网申填表"一节，细则读 `$SKILL_DIR/references/webapply.md`。**仅限交互式会话**，全程需要用户在场确认。

## 无人值守总则

如果本次运行是定时任务（无人值守）：**不要**使用 AskUserQuestion 或以任何方式等待用户输入；遇到不确定情况一律按本文件和 references 中的默认策略自主处理，并在最终回复里如实说明做了什么假设。（第 0 步的初始化例外——见下文。）深评按 config 的 `resume.auto_deep_eval_when_unattended`（默认 true）自动执行；**任何情况下无人值守不得进入简历工坊、不得执行改简历、不得替用户标记任何投递状态、不得进入网申填表或执行任何浏览器写操作**；无简历档案时跳过深评，日报会自动带提示行。

## 执行步骤

### 0. 首次使用初始化（仅当尚未完成初始化时触发）

读取 `$SKILL_DIR/config.json`；如果这个文件不存在，先把 `$SKILL_DIR/config.example.json` 复制一份成 `$SKILL_DIR/config.json`。

检查 `onboarded` 字段：

- **如果 `onboarded` 不是 `true`，但当前是无人值守的定时任务运行**：不要凭空猜测方向瞎跑一通。直接在最终回复里如实说明"这个技能还没有完成初始化设置，请先手动运行一次、发一份简历并回答几个设置问题后再启用定时任务"，然后结束本次运行。

- **如果 `onboarded` 已经是 `true`**：跳过这一步，进入第 1 步。

- **如果 `onboarded` 不是 `true`，且当前是有用户在场的交互式会话**：按 `$SKILL_DIR/references/resume-profile.md` 严格串行执行下面五段。

#### 0.1 先要简历（硬门禁）

**这一步只做一件事：请用户提供简历文件**（支持 PDF/图片/DOCX/MD/TXT）。

> **红线：拿到简历并成功提取出文本之前，不得提出任何配置问题。** 不问届别、不问方向、不问要不要看实习、不问招聘季节。不要在同一条消息里"顺便"问。提取失败（格式读不了、文件损坏）时仍然停在这一步，请用户换个格式再发，而不是跳过去问问题。

用户第一条消息就带了简历文件 → 直接用，不要再要一次。

拿到后：`resume_store.py import-original` 存档原件 → 提取纯文本（环境能直接读就直接读，否则用 `extract_text.py`）→ 写入 `resumes/versions/<YYYYMMDD>-base/resume.txt`。

**用户明确拒绝提供简历** → 把 config 的 `resume.enabled` 置 `false`，跳过 0.2，直接进 0.3 用不带预填的四问，并说明匹配评分和改简历功能会关闭。

#### 0.2 分析简历，推荐岗位方向

按 resume-profile.md"0.2 简历分析与方向推荐"一节，**先把分析结果讲给用户看**，包含四块：①画像速览 ②优势 3 条（每条"结论 —— 简历里的证据"）③短板 2-3 条（说清会在哪一步卡住）④**推荐 2-3 个岗位方向**，每个带契合度、推荐理由（引简历证据）、典型岗位名、要补什么，并说明哪个是主推、为什么。

**红线：只能基于简历里实际写着的内容。** 简历没写就写"简历里没写，需要你补充"，不要用"应该""大概"往下推。

分析结论写进 `resumes/profile.json` 的 `strengths`/`gaps`/`recommended_directions`，然后 `resume_store.py register --id <YYYYMMDD>-base --kind base --set-active` 注册基底版本。

#### 0.3 四问确认（带预填）

按 resume-profile.md 的预填规则问 ①目标届别 ②岗位方向 ③是否含实习 ④招聘季节（含 `season_end_date`）。**方向那一问的选项直接用 0.2 的推荐**，主推排第一，最后留一个"都不是，我想投别的"。有提问工具就用选项式，没有就文字逐条列出请用户确认或纠正。

确认后归纳 `job_filter` 的 `positive_keywords`（主要来自确认方向的 `typical_titles`）/`fuzzy_keywords`/`negative_keywords`（`intern_exclusion_keywords`/`formal_recruit_keywords` 用模板默认值即可）。

#### 0.4 生成公司池

按确认后的方向生成 30-50 家"该方向常开校招"的公司名写入 `discovery.company_watchlist`，展示给用户并说明可随时增删。

#### 0.5 落盘

把以上全部写进 `$SKILL_DIR/config.json`，置 `onboarded: true`，用一段话向用户复述设置摘要（方向、届别、季节、实习与否、公司池家数、发现层是精简轮转模式），再继续第 1 步。

### 1. 读取配置与档案

建好并清空临时目录，避免上次运行的残留串进这次日报：

```
mkdir -p $SKILL_DIR/state/tmp && find $SKILL_DIR/state/tmp -name '*.json' -delete
```

（用 `find` 不用 `rm dir/*.json`：后者在 zsh 下没有匹配文件时会报错中断整个流程。）

读取 `$SKILL_DIR/config.json`。**缺 `resume`/`discovery`/`applications`/`deadline` 块**（老用户升级场景）→ 从 `config.example.json` 把缺的块补进 config.json 再继续。然后：

```
python3 $SKILL_DIR/scripts/resume_store.py status --resumes $SKILL_DIR/resumes
```

- `resume.enabled` 为 true 但档案为空（无 active_base）：**交互式会话** → 按 resume-profile.md"老用户补传"一节提议补传（走 0.1 → 0.2 再回来）；**无人值守** → 本次跳过深评。
- 档案就绪：读 `resumes/profile.json` 备用；再跑 `python3 $SKILL_DIR/scripts/insights.py show --insights $SKILL_DIR/state/match_insights.json`，输出留给深评和简历工坊当证据。

下文 `{job_category_label}`、`{target_grad_year}`、`{target_season_label}`、`{profile_summary}` 均指代实际值。

### 2. 规划本次发现

```
python3 $SKILL_DIR/scripts/discovery.py plan \
  --config $SKILL_DIR/config.json --state $SKILL_DIR/state/seen_postings.json \
  --output $TMP/plan.json
```

**今天跑哪几路、每路用什么模型、公司池查哪一批、已监控公司名单，全部以 `plan.json` 为准**，不要自己判断轮转或加路数。默认策略：公众号两路每天跑，聚合平台每周一次全量日跑；首次运行强制全量。

### 3. 按计划并行发现

先读 `$SKILL_DIR/references/sources.md`，然后对 `plan.json` 的 `lanes` 数组里的**每一条**车道，用 Agent 工具在**同一条消息里并行**发起一个子任务（general-purpose 类型，模型用该车道的 `model` 字段；环境不支持指定模型就省略）。

每个子 agent 的 prompt 必须：

- 以「{联网句}」开头。
- 说明该车道要干什么（sources.md"车道定义"里对应那条），把 `{job_category_label}`/`{target_grad_year}`/`{target_season_label}` 的实际值代入，不指定方法动词。
- 追加候选人画像 `{profile_summary}`（不含任何个人身份信息），要求优先关注与画像契合的岗位。
- `wechat-watchlist` 这一路要把 `plan.json` 给出的 `batch` 公司名单原样带进去，并写明"只查这批，不要自行扩展名单"。
- 带上 `plan.json` 的 `known_companies`，写明"这些公司已在库，它们**已有的**岗位不用再报；只有它们**新开**的岗位（岗位名称不同）才报；名单外的公司照常报"。
- 带上该车道的 `scope_hint` 作为范围上限。
- **规定输出契约**：「最终回复只输出一个 JSON 数组，不要任何前言、说明、总结文字。字段：`company`、`title`、`city`（无法判断写"未注明"）、`highlight`（≤30字）、`source_url`（完整含参数）、`source_platform`、`deadline`（YYYY-MM-DD，页面没写填 null）。最多 20 条，按相关度排序。」
- 说明：来源当天不可用就直接返回 `[]`，不要反复重试、不要解释。
- **显式禁止子 agent 再自行派发下一层子 agent**。

等待全部返回；某路为空或失败不影响其余结果。**弱环境（无子 agent 能力）**：按 sources.md"弱环境降级"节顺序执行。

### 4. 合并 + 过滤

把各路结果合并成一个数组，**给每条候选加上 `lane` 字段**（值 = 它来自哪条车道的 lane id，`discovery.py` 靠它统计产出）。读 `$SKILL_DIR/references/keyword-filters.md` 了解过滤逻辑，按 `config.json` 的 `job_filter` 执行：

- 命中 `positive_keywords` 任一 → 保留。
- 命中 `fuzzy_keywords`、但未注明具体方向 → 保留，标题末尾加 `[方向待确认]`。
- 命中 `intern_exclusion_keywords`（含"实习转正"）→ 排除；**但 `include_internships` 为 `true` 时这条整体跳过**。
- 明确写出早于 `target_grad_year` 的届别 → 排除。
- 其余按 keyword-filters.md 处理；地域不过滤，`city` 照抄原文。

把过滤后的候选列表写成 JSON 数组文件 `$TMP/candidates.json`（字段同上，含 `lane` 和 `deadline`）。

### 5. 去重

```
python3 $SKILL_DIR/scripts/dedupe.py \
  --input $TMP/candidates.json \
  --state $SKILL_DIR/state/seen_postings.json \
  --config $SKILL_DIR/config.json \
  --output $TMP/new-only.json
```

这一步会原地更新 state（新岗位写入并携带永久 `id`、已见岗位刷新 `last_confirmed`、过截止日期的标记 `expired`、过季自动归档），并把真正新增的岗位输出到 `--output`。

如果它在 stderr 提示**上一季已归档**，在最终回复里转达，并问用户 config 的 `target_grad_year`/`target_season_label`/`season_end_date` 要不要滚动到新一季（无人值守就只转达，不改）。

### 6. 回写发现账本

```
python3 $SKILL_DIR/scripts/discovery.py commit \
  --config $SKILL_DIR/config.json --state $SKILL_DIR/state/seen_postings.json \
  --plan $TMP/plan.json
```

推进公司池游标、记录全量扫描日期、累计各车道产出。**必须在第 5 步之后跑**（它要读 dedupe 算出的本次各路新增数），漏跑会导致公司池永远轮询同一批。

### 7. 核实新公司（可选，有上限）

在 `$TMP/new-only.json` 中，找出"公司此前从未出现过"的记录。最多取 5 家这样的新公司，为每家发起一个子 agent（用聚合路的便宜模型；prompt 以「{联网句}」开头，目标是"在该公司官方校园招聘官网核实这个岗位是否存在，若存在返回权威链接和网申截止日期"；同样禁止再派子 agent）。核实到官方链接就编辑 new-only 文件和 state 中对应记录的 `source_url`/`source_platform`/`deadline`（`id` 保持不变）；发现届别不符就从两处移除该记录。核实失败或超过 5 家上限的保留原链接。弱环境：跳过本步。

### 8. JD 深评（每个新岗位抓 JD 打匹配分）

`resume.enabled` 为 false、或简历档案为空 → **整步跳过**。规则细节读 `$SKILL_DIR/references/matching.md`。

- 8.1 选待评：`python3 $SKILL_DIR/scripts/match_state.py pending --state $SKILL_DIR/state/seen_postings.json --config $SKILL_DIR/config.json --profile $SKILL_DIR/resumes/profile.json --output $TMP/pending.json`（上限、快评排序、跳过已评和已过期，全在脚本内）。
- 8.2 抓 JD：把 pending 数组按每 5 条一组，最多 `resume.jd_fetch_parallel_agents` 个子 agent 并行，模型用 `resume.jd_fetch_agent_model`（默认 haiku），prompt 用 matching.md 的契约模板原文（子 agent 只抓不评分，要抓 `deadline`）。**弱环境**：自己逐条串行抓，条数减半。
- 8.3 统一评分：由你（orchestrator）按 matching.md 的五维量表，对照 `profile.json`（含 `strengths`/`gaps`）+ 第 1 步的 insights 输出逐条打分，写 `$TMP/evaluated.json`（抓不到的写 `fetched:false` + reason）。证据不足的项按缺失计，禁止脑补。**评分不下放给子 agent**。
- 8.4 落库：`python3 $SKILL_DIR/scripts/match_state.py record --state $SKILL_DIR/state/seen_postings.json --config $SKILL_DIR/config.json --input $TMP/evaluated.json`，然后 `python3 $SKILL_DIR/scripts/insights.py ingest-eval --insights $SKILL_DIR/state/match_insights.json --input $TMP/evaluated.json`。

### 9. 渲染日报

```
python3 $SKILL_DIR/scripts/digest.py render \
  --new $TMP/new-only.json \
  --state $SKILL_DIR/state/seen_postings.json \
  --config $SKILL_DIR/config.json \
  --evaluated $TMP/evaluated.json \
  --resumes $SKILL_DIR/resumes \
  --applications $SKILL_DIR/state/applications.json \
  --plan $TMP/plan.json \
  --date $(date +%F) > $TMP/digest.md
```

（第 8 步被跳过时省略 `--evaluated`。`--applications` 指向的文件不存在也没关系，脚本自己会当空处理。）

### 10. 输出与一键入口

最终回复内容 = `$TMP/digest.md` 的完整内容，原样输出，不需要额外包装。无论有没有新增岗位都必须输出日报，不要空手结束任务。**精简日发现不到新岗位是正常的**，页脚已经写明今天只扫了几路，不要因此自作主张加路数重跑。

输出日报后，**仅交互式会话**再做一步：取本次 `score >= resume.min_score_for_action` 的岗位——

- 有提问工具：选项式提问（最多 4 个岗位选项 + "先不改"），用户选中即携带该岗位进入简历工坊 W1。这就是"一键改简历"。
- 无提问工具：在日报尾追加编号岗位清单和一句"回复编号即可为该岗位定制简历"。

**无人值守：输出日报即结束。**

## 简历工坊

四个子入口（无人值守一律不进入本节）：

- **定制简历**（一键选中的岗位，或用户贴 JD/说"帮我改简历投XX"）：完整执行 `$SKILL_DIR/references/tailoring.md` 的 W1-W7——选基底（先看 `apply.py stats --by-version`，过筛率明显偏低的版本不要再当基底）、诚实性核查（先查 insights 已沉淀素材，不重复问；新答案立刻 add-fact）、STAR + 实事求是改写、kami 渲染（渲染前必须跑 `build.py --check-placeholders` 确认无漏填占位符；缺 WeasyPrint 降级 HTML）、四件套存档注册、交付改动清单与前后分数。**诚实性核查（W3）、STAR 实事求是（W4）和占位符检查在任何环境都不可跳过；每次产出必须 register 存档。** 交付后问一句"投了吗"，用户说投了就按"投递追踪"记一笔；用户说要去官网网申的，可以直接转入"网申填表"（路由 E）用这一版简历填表。
- **单个 JD 现评**（用户贴 JD 问匹配度）：按 `references/matching.md` 量表现场打分并给一句优势/一句差距，不写入 state；用户接着要改简历就把分数当 `score_before` 转入定制流程。
- **查看档案**：`python3 $SKILL_DIR/scripts/resume_store.py list --resumes $SKILL_DIR/resumes`，需要细节时展示对应版本目录下的 `meta.json`。
- **重看简历分析 / 换方向**：读 `resumes/profile.json` 的 `strengths`/`gaps`/`recommended_directions` 复述，不要重新分析（除非简历换过）。换方向按 resume-profile.md 末节重新归纳 `job_filter` 和 watchlist 写回 config。

## 投递追踪

细则读 `$SKILL_DIR/references/applications.md`。无人值守只读不写。

- **记一次投递**（改完简历用户说要投，或用户说"我投了XX"）：`apply.py mark --applications $SKILL_DIR/state/applications.json --state $SKILL_DIR/state/seen_postings.json --posting-id <岗位id> --resume-version <版本id>`。岗位在监控库里就一定用 `--posting-id`（公司名/岗位名/截止日期自动带过来，还能让日报别再催这个岗位）；库外的岗位用 `--company` + `--title`。
- **更新进展**（"XX让我去笔试了""一面过了""挂了"）：`apply.py stage --applications ... --id <id或公司名关键字> --stage <阶段>`，有约好的时间就带 `--next-action YYYY-MM-DD`。模糊匹配到多条时脚本会列出候选，**让用户选，不要自己猜**。
- **查询**：`apply.py list`（在投的用 `--open-only`）、`apply.py stats --by-version`（各版本过筛率；样本少时只能当参考，如实说明）。
- 日报里的"📮 投递待跟进"是 `digest.py` 自动渲染的，不需要额外调用。

## 网申填表

细则读 `$SKILL_DIR/references/webapply.md`。**无人值守绝不进入本节**，全程需要用户在场。

**前置**：加载 `web-access`（加载不了就读 `~/.claude/skills/web-access/SKILL.md`）→ 跑 `check-deps.mjs` → **原文向用户展示它的自动化封号风险提示** → 起／复用 `cdp-proxy.mjs` 并 `curl localhost:3456/health` 探活。起不来就走降级（见下）。
`resumes/webapply-profile.json` 不存在或 `completion.status != "ready"` → 先做 webapply.md 第 2 节的档案初始化（抽取 → 分块核对 → 补问缺口 → 落盘）。

**安全红线（这几条必须在这里也看得见，不许只写在 references 里）**：

1. 密码、验证码、身份证号/护照号、银行卡号 —— **绝不代填、绝不存档案**。表单遇到就截图指位、请用户手填，填完不回读该值。
2. **绝不代注册账号、绝不代过验证码/滑块/人机验证**，登录一律用户本人在 Chrome 完成。
3. 填写前用户须确认字段映射；**每一次**点「提交/确认投递」这类不可逆按钮前都要重新拿到用户明确同意——不存在"本次会话已授权"。默认停在提交前。
4. 只在自己 `/new` 开的后台 tab 里操作，不碰用户已有 tab，做完 `/close`。
5. 档案内容和页面截图**永不进子 agent prompt、永不外发**；pattern 经验文件只记结构与选择器，绝不写个人数据或答案文本。

**流程一句话版**：开 tab → 判断登录态（读不到内容才请用户登录）→ 读 `webapply-patterns/` 已有经验 → `/eval` 读 DOM 出**字段映射预览表**（缺的当场问、问完写回档案，红线字段标"需你手填"）→ 用户确认 → 逐节填写，每节读回校验 + 截图存 `state/tmp/webapply/<时间戳>/` → 多步向导的"保存/下一步"可直接点 → **提交前停下**汇总请用户核对 → （用户同意提交且真的提交成功后）`apply.py mark ... --channel 官网网申`（库内岗位用 `--posting-id`，库外用 `--company` + `--title` + `--note <网申链接>`）→ 写回 pattern 经验（存盘前 grep 自检无 PII）→ `/close`。

**降级**（CDP 起不来）：不做浏览器操作，档案初始化照常，改为产出「字段-答案清单」表格给用户复制粘贴手填，开放题附全文。
