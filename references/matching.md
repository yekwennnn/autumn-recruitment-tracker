# JD 深评：抓取契约、评分量表与数据 schema

本文档是深评管线（SKILL.md 第 6 步）和"单个 JD 现评"（简历工坊）的权威规则。

## 管线时序

1. `match_state.py pending` 选出本次待深评岗位（上限、快评排序、永不重选已评岗位，全在脚本里）。
2. 并行子 agent **只抓 JD、不打分**（契约见下）。
3. **orchestrator 统一评分**——评分绝不下放给子 agent：保证所有岗位用同一把尺子，且 profile 与 insights 只需读一份。
4. `match_state.py record` 写回 state + `insights.py ingest-eval` 累计需求词频。

```
python3 $SKILL_DIR/scripts/match_state.py pending \
  --state $SKILL_DIR/state/seen_postings.json --config $SKILL_DIR/config.json \
  --profile $SKILL_DIR/resumes/profile.json \
  --output /tmp/autumn-recruitment-pending.json
# ...抓取 + 评分，写 /tmp/autumn-recruitment-evaluated.json...
python3 $SKILL_DIR/scripts/match_state.py record \
  --state $SKILL_DIR/state/seen_postings.json --config $SKILL_DIR/config.json \
  --input /tmp/autumn-recruitment-evaluated.json
python3 $SKILL_DIR/scripts/insights.py ingest-eval \
  --insights $SKILL_DIR/state/match_insights.json \
  --input /tmp/autumn-recruitment-evaluated.json
```

## 抓 JD 子 agent 契约

分配规则：每个子 agent 分 **不超过 5 条** 岗位；并行 agent 数不超过 config 的 `resume.jd_fetch_parallel_agents`。**弱环境（无子 agent 能力）**：orchestrator 自己逐条串行抓，且本次深评条数按上限减半执行。

prompt 模板（`{联网句}` 按 SKILL.md 降级表选版；`{N}` 与岗位列表来自 pending 输出）：

```
{联网句}
以下是 {N} 个校招岗位（JSON 数组，含 id/company/title/source_url）。对每一条：
访问 source_url 获取该岗位完整JD；若该链接打不开或无JD详情，检索该公司官方校招网站上的对应岗位页。
返回 JSON 数组，每条字段：
  id（原样带回，不得改动）、fetched（true/false）、jd_url（最终JD页链接）、
  jd_summary（≤150字，必须覆盖：硬性要求一句/优先项一句/工作内容一句）、
  jd_keywords（≤10个名词，如 Python/SQL/CPA）。
不要打分。抓不到就如实 fetched:false 并附 reason；单条最多尝试两种途径，禁止反复重试。
【重要】必须自己直接完成调研，不得调用 Agent 工具再派发子任务。
岗位列表：{pending 数组的 JSON}
```

## 评分量表（0-100 整数，五维加总）

| 维度 | 满分 |
|---|---|
| 硬技能匹配（语言/工具/专业技能 vs JD 硬性要求） | 35 |
| 经验与项目相关度（实习/项目/社团 vs 岗位职责） | 25 |
| 学历/届别/专业 | 15 |
| 证书与语言（CPA/法考/六级/雅思…） | 10 |
| 加分项与意向契合（城市/行业偏好/软技能） | 15 |

打分规则：
- 证据来源**只有两处**：`resumes/profile.json` + `state/match_insights.json` 的 `confirmed_facts`（先跑 `insights.py show` 拿到）。
- **JD 硬性要求在两处都无证据 → 该项按缺失计，禁止脑补"应该会"**——与改简历的实事求是红线同源。
- 每条输出必含：`score`（整数）、`pros`（一句 ≤40 字优势）、`gaps`（一句 ≤40 字差距）、`jd_keywords`。

## 分档（与 digest.py 顶部常量严格一致，改一处必须同步另一处）

| 分数 | 档位 |
|---|---|
| ≥85 | 高度匹配 |
| 70-84 | 推荐投递 |
| 50-69 | 备选 |
| <50 | 观望 |

`score >= resume.min_score_for_action`（默认 70）的岗位：日报标"建议一键定制简历"，并进入第 8 步的一键选项列表。

## 成本与幂等

- 单次深评上限 `resume.max_deep_evals_per_run`（默认 15）；超出的按快评分排序自动排队，日报标"待深评（下次运行自动补评）"。
- 抓取失败累计 `resume.jd_fetch_max_attempts` 次（默认 2）后封顶为 `jd_unavailable`，不再尝试，日报标"JD未抓到，未评分"。
- `scored` 的岗位**永不重评**。只有用户明确说"重新评估XX岗位"时，才重抓重打并用 `record --force` 覆盖。

## 数据 schema 汇总

### state/seen_postings.json 中的 posting 记录（schema_version 2）

```json
"<sha1>": {
  "id": "<sha1>", "company": "...", "title": "...", "city": "...",
  "highlight": "...", "source_platform": "...", "source_url": "...",
  "first_seen": "2026-07-24", "last_confirmed": "2026-07-24",
  "match": {
    "status": "pending | scored | jd_unavailable",
    "quick_score": 4, "jd_fetch_attempts": 0, "last_fetch_error": null,
    "jd_url": "", "jd_summary": "", "jd_keywords": [],
    "score": null, "pros": "", "gaps": "",
    "evaluated_at": "", "resume_version": ""
  }
}
```

`match` 字段只由 `match_state.py` 写（dedupe.py 不碰它）；state 顶层另有 `wechat_rotation_cursor`（公众号轮询游标，orchestrator 读写，见 sources.md 第 2 路）。

### /tmp/autumn-recruitment-evaluated.json（orchestrator 评分后写）

```json
[
  { "id": "<sha1>", "fetched": true, "jd_url": "...", "jd_summary": "≤150字", "jd_keywords": ["Python"], "score": 84, "pros": "一句优势", "gaps": "一句差距", "resume_version": "20260724-base" },
  { "id": "<sha1>", "fetched": false, "reason": "页面需登录" }
]
```

读方：`match_state.py record`、`insights.py ingest-eval`、`digest.py render --evaluated`（渲染"本次补评完成"小节）。

### state/match_insights.json（"越来越智能"的载体，只由 insights.py 写）

```json
{
  "schema_version": 1,
  "updated_at": "2026-07-24T09:00:00+08:00",
  "jd_demand_stats": { "Python": { "count": 12, "last_seen": "2026-07-24" } },
  "confirmed_facts": [
    { "claim": "用扣子搭过简历初筛工作流", "detail": "触发=表单提交，输出=飞书表格，个人使用", "stage": "demo", "confirmed_at": "2026-08-01" }
  ],
  "version_performance": [
    { "version": "20260801-tencent-fengkong", "tags": ["风控"], "score_after": 84, "target": "腾讯-金融科技风控岗", "date": "2026-08-01" }
  ],
  "notes": [ { "text": "该方向JD普遍要求SQL，简历里SQL证据应前置", "date": "2026-08-01" } ]
}
```

读写时机：深评打分前和改简历 W3 前 `show`（注入 prompt 当证据）；每次 record 后 `ingest-eval`；诚实性核查问出新素材 → `add-fact`；注册定制版后 → `log-version`；发现规律性经验 → `note`。

## 单个 JD 现评（简历工坊入口）

用户直接贴来的 JD：按同一量表、同一证据规则现场打分并给 pros/gaps，**不写入 state**（它不是监控发现的岗位）；若用户随后要求改简历，分数直接作为 `score_before`。
