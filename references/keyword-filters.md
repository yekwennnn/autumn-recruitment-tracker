# 岗位方向过滤规则

关键词列表统一维护在 `config.json` 的 `job_category_label` 和 `job_filter` 字段里，本文档只描述过滤**逻辑**本身，不写死任何具体行业的关键词——换一个岗位方向（技术/市场/人力资源/供应链/产品……），只需要改 `config.json`，不需要改这份文档或 `SKILL.md`。这些字段不会预设成任何具体行业，首次使用时由 `SKILL.md` 第 0 步的初始化提问收集并写入。

`job_filter` 下有 4 组关键词数组：`positive_keywords`（正向）、`fuzzy_keywords`（模糊）、`negative_keywords`（负向）、`intern_exclusion_keywords`（实习排除）、`formal_recruit_keywords`（正式校招确认信号）。

## 过滤时机

过滤在 orchestrator 合并所有子 agent 结果**之后**统一执行一次，不在各子 agent 内部做（子 agent 只管尽量多收集，保证召回率，硬过滤会在发现阶段静默丢失真正符合方向的岗位）。

## 正向关键词（命中 `job_filter.positive_keywords` 任一即视为目标方向）

命中即保留。

## 模糊情况（命中 `job_filter.fuzzy_keywords`，不硬过滤）

未注明具体方向、但命中模糊关键词（例如"管理培训生"）的岗位——不要因为标题没写明确方向就直接丢弃，保留该条目并在标题末尾标注 `[方向待确认]`，交给用户自己判断。此阶段召回率优先于精确率。

## 负向关键词（命中 `job_filter.negative_keywords`，仅在完全没有正向命中时用于二次确认排除）

## 实习排除（命中 `job_filter.intern_exclusion_keywords` 一律排除，除非用户选择了包含实习）

如果 `config.json` 的 `include_internships` 为 `true`（用户在初始化提问时选择了"也要看实习"），这条规则整体跳过，实习岗位正常保留、不做区分。

`include_internships` 为 `false`（默认）时：即使标注"实习转正"也排除，无论是否也命中 `formal_recruit_keywords`——实习排除词优先级高于正式校招确认信号。

## 正式校招确认信号（`job_filter.formal_recruit_keywords`，以及 `target_grad_year` 对应的"届"字样，如"2027届"）

命中即视为正式校招；与实习排除词冲突时以实习排除词优先。

## 届别过滤

明确写出早于 `target_grad_year` 配置值的届别（例如目标是 2027 届，岗位明确写"2026届"或更早）排除。未明确写届别、但符合 `target_season_label` 对应招聘周期的岗位默认保留。

## 地域

不做地域过滤——除非用户在 `config.json` 或对话中明确要求限定地域，只需如实记录 `city` 字段（原文照抄；完全无法判断时记"未注明"）。