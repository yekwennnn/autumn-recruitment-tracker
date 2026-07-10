---
name: autumn-recruitment-tracker
description: >
  监控全国范围校园招聘中新开放的正式校招岗位，目标岗位方向/届别/招聘季节/是否含实习
  均由 config.json 配置驱动，可用于任意行业方向。首次使用时会主动向用户提问确认这些
  设置，不预设任何默认方向。去重后生成日报。当需要手动触发一次监控、检查监控状态、
  或修改监控方向/关键词/公司范围时使用此技能。
version: "1.0.0"
user_invocable: true
metadata:
  author: yekaiwen
  version: "1.0.0"
---

# 秋招岗位监控

目录约定（不要写死用户名、家目录或安装位置）：

```
SKILL_DIR=.
```

执行本文件中的命令时，以当前这份 `SKILL.md` 所在目录作为工作目录，并使用相对于该目录的路径。所有配置、状态、脚本和参考文档都从这里解析，禁止使用发布者机器上的绝对路径或固定技能 ID。

- 配置：`$SKILL_DIR/config.json`（目标届别/季节/岗位方向/是否含实习/关键词，全部在这里改，不需要碰代码或其他文档；首次使用时该文件可能不存在或 `onboarded` 为 `false`，见第 0 步）、`$SKILL_DIR/config.example.json`（未初始化时的模板，不要直接改这个文件）
- 状态：`$SKILL_DIR/state/seen_postings.json`
- 脚本：`$SKILL_DIR/scripts/dedupe.py`、`$SKILL_DIR/scripts/digest.py`
- 参考文档：`$SKILL_DIR/references/sources.md`（数据源与兜底策略）、
  `$SKILL_DIR/references/keyword-filters.md`（岗位方向/实习/届别过滤逻辑，具体关键词读 config.json）、
  `$SKILL_DIR/references/digest-format.md`（日报格式，仅供理解 `digest.py` 输出，不需要手写格式化逻辑）。

如果本次运行是定时任务（无人值守）：**不要**使用 AskUserQuestion 或以任何方式等待用户输入；遇到不确定情况一律按本文件和 references 中的默认策略自主处理，并在最终回复里如实说明做了什么假设。（第 0 步的初始化提问例外——那一步专门规定了无人值守场景下应该怎么做，见下文。）

## 执行步骤

### 0. 首次使用初始化（仅当尚未完成初始化时触发）

读取 `$SKILL_DIR/config.json`；如果这个文件不存在，先把 `$SKILL_DIR/config.example.json` 复制一份成 `$SKILL_DIR/config.json`。

检查 `onboarded` 字段：

- **如果 `onboarded` 不是 `true`，且当前是有用户在场的交互式会话**（不是无人值守的定时任务）：这是用户第一次使用这个技能，此时**不要**凭空瞎猜方向直接开始搜索，必须先通过对话（优先用 AskUserQuestion 等提问工具，没有就直接用文字提问）向用户确认这几个找工作的人最关心的问题：
  1. **目标届别**——比如"2027届"，也可以是社招/无届别限制。
  2. **想投递的行业/岗位方向**——用大白话描述就行，比如"技术开发，前端后端都要"、"市场营销"、"财务"、"不限方向"。不需要用户自己列关键词——拿到回答后，由你自己根据这个行业方向的常见细分职能，归纳出一组合理的 `positive_keywords`（覆盖该方向常见的岗位名称/职能词）、可选的 `fuzzy_keywords`（比如笼统的"管理培训生"）、以及几个明显不相关方向作为 `negative_keywords` 兜底。
  3. **要不要包含实习岗位**——只要正式校招，还是也要看实习/实习转正。
  4. **对应的招聘季节**——比如"2026秋招"还是"2026春招"，用于生成 `target_season_label`；并据此推算一个合理的 `season_end_date`（这一季大概什么时候结束、该归档重来，秋招一般到次年2月左右，春招一般到当年7月左右，不需要再单独问用户，除非用户主动想自定义）。

   问完之后，把这些信息写进 `$SKILL_DIR/config.json`（`target_grad_year`、`target_season_label`、`season_end_date`、`job_category_label`、`include_internships`、`job_filter.positive_keywords`/`fuzzy_keywords`/`negative_keywords`），并把 `onboarded` 设为 `true`。`job_filter.intern_exclusion_keywords` 和 `job_filter.formal_recruit_keywords` 这两组是通用的，`config.example.json` 里已经有合理默认值，一般不需要改。写完后用一段话跟用户确认一遍设置摘要，再继续往下执行第 1 步。

- **如果 `onboarded` 不是 `true`，但当前是无人值守的定时任务运行**：说明用户还没有完成初始化设置。不要凭空猜测方向瞎跑一通。直接在最终回复里如实说明"这个技能还没有完成初始化设置，请先手动运行一次、回答几个方向设置问题后再启用定时任务"，然后结束本次运行，不要往下执行发现流程。

- **如果 `onboarded` 已经是 `true`**：跳过这一步，直接进入第 1 步。

### 1. 读取配置

读取 `$SKILL_DIR/config.json`，获取 `target_grad_year`（目标届别）、`target_season_label`（季节标签）、`job_category_label`（岗位方向标签，例如"财务"）、`include_internships`（是否也要看实习）、`job_filter`（正向/模糊/负向/实习排除/正式校招确认关键词）等参数，供后续所有 prompt 使用。下文所有 `{job_category_label}`、`{target_grad_year}` 均指代这里读到的实际值。

### 2. 并行发现（4 个子 agent）

先读 `$SKILL_DIR/references/sources.md`，按其中的来源分组，用 Agent 工具在**同一条消息里并行**发起 4 个子任务（general-purpose 类型，需要能用 Skill/WebSearch/WebFetch 等联网工具）：

1. 牛客网 求职/校招板块
2. 公司招聘微信公众号 + 官网详情（搜索"XX招聘"公众号发布的秋招公告，跳转官网核实岗位）—— 这是中国大陆校招信息发布的一手链路，优先级高
3. 51job校园招聘 + 智联招聘校园 + 猎聘校园官方频道（合并一个子任务）
4. 门户/公众号"秋招名单/时间表"汇总贴 + 实习僧(shixiseng.com)（WebSearch 发现新公司名单）

每个子 agent 的 prompt 必须：
- 显式包含「必须加载 web-access skill 并遵循指引」这句话。
- 用目标性措辞下达任务，把 config.json 里的 `job_category_label`、`target_grad_year` 实际值代入（例如："调研牛客网上有哪些{job_category_label}方向的{target_grad_year}届秋招正式岗位，覆盖全国范围"），不要指定具体方法动词（不要写"用WebSearch搜索"之类）。
- 要求返回结构化列表，字段：`company`（公司名称）、`title`（职位名称）、`city`（工作城市，无法判断写"未注明"）、`highlight`（岗位亮点，一句话）、`source_url`（原始链接，保留完整参数）、`source_platform`（来源栏目名称）。
- 说明：若该来源当天无法访问或没有相关信息，直接如实汇报为空，不要反复重试同一种方式。
- **显式禁止子 agent 再自行派发下一层子 agent**（写清楚"必须自己直接完成调研，不得再调用 Agent 工具委托其他子 agent"）。实测发现子 agent 会倾向于"逐个公司开子任务核实"，导致任务树无限展开、耗时和成本失控。正确做法是用该平台自身的搜索/筛选/关键词功能一次性检索，而不是一家家公司点开核实。
- 给每个子 agent 一个明确的范围上限提示，例如"最多深入核实10-15家最相关的公司，覆盖面比逐一核实的精确度更重要"，避免无限深挖单一路径。

等待 4 个子 agent 全部返回。某个子 agent 为空或失败不影响其余结果的处理——继续往下走，不要中断整体流程。

### 3. 合并 + 过滤

把 4 份结构化列表合并成一个数组。读 `$SKILL_DIR/references/keyword-filters.md` 了解过滤逻辑，按 `config.json` 的 `job_filter` 字段执行：
- 命中 `positive_keywords` 任一 → 保留。
- 命中 `fuzzy_keywords`、但未注明具体方向 → 保留，标题末尾加 `[方向待确认]`。
- 命中 `intern_exclusion_keywords`（含"实习转正"）→ 排除，无论是否也命中 `formal_recruit_keywords`；**但如果 `config.json` 的 `include_internships` 为 `true`，这一条整体跳过，实习岗位正常保留**。
- 明确写出早于 `target_grad_year` 的届别 → 排除。
- 其余按 `references/keyword-filters.md` 中的规则处理。
- 地域不过滤，`city` 字段照抄原文。

把过滤后的候选列表写成 JSON 数组文件，例如 `/tmp/autumn-recruitment-candidates.json`（字段同上）。

### 4. 去重

运行：

```
python3 $SKILL_DIR/scripts/dedupe.py \
  --input /tmp/autumn-recruitment-candidates.json \
  --state $SKILL_DIR/state/seen_postings.json \
  --config $SKILL_DIR/config.json \
  --output /tmp/autumn-recruitment-new-only.json
```

这一步会原地更新 `state/seen_postings.json`（新岗位写入、已见岗位刷新 `last_confirmed`、过季自动归档），并把真正新增的岗位输出到 `--output` 指定的文件。

### 5. 核实新公司（可选，有上限）

在 `/tmp/autumn-recruitment-new-only.json` 中，找出"公司此前从未出现过"的记录（即该公司在 `state/seen_postings.json` 里除了这条新记录外没有其他历史岗位）。最多取 5 家这样的新公司，为每家发起一个子 agent（同样要求"必须加载 web-access skill 并遵循指引"，目标是"在该公司官方校园招聘官网核实这个岗位是否存在，若存在返回权威链接"）。

若核实到官方链接，直接编辑 `/tmp/autumn-recruitment-new-only.json` 和 `state/seen_postings.json` 中对应记录的 `source_url`/`source_platform` 字段。若核实过程中发现该岗位实际届别不符合目标届别（例如页面明确写着更早的届别），应从 `/tmp/autumn-recruitment-new-only.json` 和 `state/seen_postings.json` 中移除该记录，不计入本次新增。核实失败（官网打不开、找不到对应信息）或该公司超过 5 家上限的，保留原聚合帖链接不变，不需要额外说明。

### 6. 渲染日报

```
python3 $SKILL_DIR/scripts/digest.py render \
  --new /tmp/autumn-recruitment-new-only.json \
  --state $SKILL_DIR/state/seen_postings.json \
  --config $SKILL_DIR/config.json \
  --date $(date +%F) > /tmp/autumn-recruitment-digest.md
```

### 7. 输出最终回复

最终回复内容 = `/tmp/autumn-recruitment-digest.md` 的完整内容，原样输出即可，不需要额外包装。

无论有没有新增岗位，都必须正常输出一份日报（`digest.py render` 已经处理了"无新增"分支），不要空手结束任务。