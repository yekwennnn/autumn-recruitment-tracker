# 数据源策略（精简轮转模式）

## 重要背景（用户提供的领域知识）

中国大陆校园招聘信息的发布路径通常是：**公司先通过自己的招聘官方微信公众号（一般名为"XX招聘"/"XX校园招聘"）发布"秋招正式启动"的推文**，推文里会附上跳转到**公司官方招聘官网/招聘系统**（如 zhaopin.xxx.com、campus.xxx.com、或第三方 SaaS 如北森/大易/Moka 搭建的官网）的链接，官网上才有完整的岗位列表和详细要求。第三方聚合平台（牛客网、猎聘校园等）上的信息大多是转载或用户自发讨论，时效性和完整度不如"公众号公告 → 官网详情"这条一手链路。

这条领域知识直接决定了成本分配：**公众号一手链路每天跑，聚合平台一周跑一次**。聚合平台是二手转载，日间变化极小，天天全量扫是重复付费；而"今天谁开秋招了"这个时效信号只有公众号新公告能给，一天都不能停。

## 谁决定今天跑哪几路

**`scripts/discovery.py plan` 是唯一裁决者**，orchestrator 不要自己判断轮转、批次或降频：

```
python3 $SKILL_DIR/scripts/discovery.py plan \
  --config $SKILL_DIR/config.json --state $SKILL_DIR/state/seen_postings.json \
  --output $SKILL_DIR/state/tmp/plan.json
```

输出的 `plan.json` 里已经算好：今天是精简日还是全量日、跑哪几条车道、每条用哪个模型、公司池本轮批次是哪几家、已监控公司名单、下一个 cursor。照着 `lanes` 数组发子 agent 即可。

发现＋去重跑完后必须回写账本（推进 cursor、记录全量日、累计各路产出）：

```
python3 $SKILL_DIR/scripts/discovery.py commit \
  --config $SKILL_DIR/config.json --state $SKILL_DIR/state/seen_postings.json \
  --plan $SKILL_DIR/state/tmp/plan.json
```

## 车道定义（lane）

| lane id | 名称 | 频次 | 渠道 |
|---|---|---|---|
| `wechat-launch` | 公众号-新启动公告扫描 | 每天 | wechat |
| `wechat-watchlist` | 公众号-公司池轮询 | 每天（每次一批） | wechat |
| `roundup-newcompany` | 汇总帖挖新公司→公众号核实→官网 | 全量日 | aggregator |
| `aggregator-nowcoder` | 牛客网校招板块 | 全量日 | aggregator |
| `aggregator-campus` | 51job校园+智联校园+猎聘校园 | 全量日 | aggregator |
| `aggregator-intern` | 实习僧 | 全量日，且仅 `include_internships` 为 true | aggregator |

各路要干什么：

1. **`wechat-launch`** — 找最近 3 天新发布的"{target_season_label}正式启动/启动"类招聘公众号推文（公众号一般名为"XX招聘"/"XX校园招聘"），优先经搜狗微信搜索（weixin.sogou.com）等公众号内容检索入口；找到推文后跳转文内的公司官方招聘网站链接，核实 {job_category_label} 方向、{target_grad_year} 届的岗位详情。这是最快发现"今天谁开秋招了"的一手信号，**任何情况下都不降频**。

2. **`wechat-watchlist`** — 对 `plan.json` 里给出的 `batch`（本轮批次公司名）逐家检索其招聘公众号近 30 天推文，发现新公告即跳官网拿岗位详情。批次由 `discovery.py` 按 `wechat_rotation_cursor` 切好，子 agent **只查批次里列的公司，不要自行扩展名单**；几天内能把整个公司池轮一遍。

3. **`roundup-newcompany`** — 先从"{target_season_label} 名单/时间表/已开启"类汇总帖（门户、公众号转载帖）挖出**近两周刚开启**这一季校招的公司名，再对其中与 {job_category_label} 方向最相关的至多 12 家，逐家检索其招聘公众号推文核实、并跳官网拿岗位详情。汇总帖本身是二手信息，这条路的价值在"名单 → 公众号 → 官网"的完整核实链。

4. **`aggregator-nowcoder`** — 牛客网（nowcoder.com）求职/校招板块，应届生一手讨论区，信息量最大。

5. **`aggregator-campus`** — **51job校园招聘**（campus.51job.com）+ **智联招聘校园**（xiaoyuan.zhaopin.com）+ **猎聘校园**（campus.liepin.com），结构相似合并为一路，用 `job_category_label` 的值作为频道内筛选词。

   > **2026-07-08 更新**：应届生求职网（yjbys.com）经实测已停用校园招聘频道（只剩简历模板/求职百科内容，历史招聘专题页返回 404/403），**不再作为数据源**。

6. **`aggregator-intern`** — 实习僧（shixiseng.com）。`include_internships` 为 false 时 `discovery.py` 会自动跳过这一路：该站产出全是实习岗，会在过滤步骤被整批丢掉，跑它纯属浪费。

## 精简日 / 全量日

- **精简日**：只跑 `tier=daily` 的两条公众号路。
- **全量日**：所有可用车道跑满，用来补精简日可能漏掉的岗位。触发条件（`discovery.py` 内部判定，满足其一即可）：
  - 今天是 `discovery.full_sweep_weekday`（默认 6 = 周日）；
  - 距上次全量已满 7 天（防止定时任务某天没跑成导致一直不全量）；
  - **首次运行**（state 里还没有 `last_full_sweep`）——第一天必须铺满，否则用户第一份日报会空得离谱。
- `discovery.mode` 设成 `"full_daily"` 则每天全量（成本回到旧版水平，只在用户明确要求时改）。

## 模型分层

发现层干的是"检索 + 抽取结构化列表"，不需要深度推理，因此**发现层子 agent 一律用便宜模型**，`plan.json` 每条车道的 `model` 字段已经给好（来自 `config.discovery.agent_model`，默认公众号路 `sonnet`、聚合路 `haiku`）。发子 agent 时把这个值传给 Agent 工具的模型参数。

**评分绝不下放**：合并、过滤、JD 深评打分全部仍由 orchestrator 亲自做，保证所有岗位用同一把尺子。降的是检索的价，不是判断的质。

环境的 Agent 工具不支持指定模型时，忽略 `model` 字段照常发起即可，其余机制不受影响。

## 已监控公司负向提示（省钱的第二个来源）

`plan.json` 的 `known_companies` 是已经在库的公司名单。每个发现层子 agent 的 prompt 都要带上它，并写明：

> 以下公司已经在监控库里：{known_companies}。它们**已有的**岗位不用再报。只有当你发现这些公司**新开**了库里没有的岗位（岗位名称不同），才需要报出来；名单外的公司一律照常报。

季节越往后，重复率越高，这一条省得越多。注意措辞要准确——**公司重复不等于岗位重复**，别让子 agent 把老公司新开的岗位一起吞掉。

## 子 agent 调用约定

每个发现层子 agent 的 prompt 必须：

- 以「{联网句}」开头（按 SKILL.md"环境能力自检与降级"表选择对应版本）。
- 用目标性措辞下达任务，把 `job_category_label`、`target_grad_year`、`target_season_label` 的实际值代入（例如"调研牛客网上有哪些{job_category_label}方向的{target_grad_year}届秋招正式岗位"），不要指定具体方法动词（不要写"用WebSearch搜索"之类），把搜索/抓取/升级的路由决策留给联网工具自己判断。
- 追加一段候选人画像 `{profile_summary}`（来自 `resumes/profile.json`，两三句话，不含任何个人身份信息），让子 agent 优先关注与画像契合的岗位。
- 带上上一节的已监控公司名单与说明。
- 带上该车道的 `scope_hint`（`plan.json` 里给了）作为范围上限，避免无限深挖单一路径。
- **规定输出契约**（这是省 token 的第三个来源——子 agent 的回复正文是 orchestrator 要付费读进来的）：

  > 最终回复**只输出一个 JSON 数组，不要任何前言、说明、总结或 markdown 代码块以外的文字**。每个元素字段：`company`、`title`、`city`（无法判断写"未注明"）、`highlight`（一句话亮点，≤30字）、`source_url`（完整含参数）、`source_platform`、`deadline`（网申截止日期 YYYY-MM-DD，页面没写就填 null）。最多 20 条，按相关度排序。

- 说明：若该来源当天无法访问或没有相关信息，直接返回 `[]`，不要反复重试同一种方式，也不要解释为什么是空的。
- **显式禁止子 agent 再自行派发下一层子 agent**（写清楚"必须自己直接完成调研，不得调用 Agent 工具委托其他子 agent"）。

拿到各路结果后，orchestrator 合并时**必须给每条候选加上它来自哪条车道的 `lane` 字段**（值 = plan.json 里的 lane id）——`dedupe.py` 靠它统计各路产出。

## 弱环境降级（无子 agent 能力时）

顺序执行 `plan.json` 里列出的车道，每路范围减半（最多深入核实 5-8 家公司）。精简日只有 2 路，串行跑也不算慢；全量日车道多，可以只跑前 3 条并在最终回复里如实说明本次是精简模式。

## 核实层（顺序执行，仅针对本次新出现的公司）

对 state 中全新出现的公司（即 `state/seen_postings.json` 里没有记录过的公司名），访问其**官方校园招聘官网**核实岗位、获取权威链接替换聚合帖/公众号链接。每次运行最多核实 5 家新公司，避免每日成本无限增长。已在 state 中出现过的公司不重复核实。这一步同样用便宜模型。

## 产出率统计与自动降频

`state/seen_postings.json` 顶层的 `source_yield` 记录每条车道跑了多少次、贡献了多少新增岗位、其中多少条深评达到 `min_score_for_action`、连续零产出多少次。查看：

```
python3 $SKILL_DIR/scripts/discovery.py yield-report --state $SKILL_DIR/state/seen_postings.json
```

某条车道连续 `discovery.auto_demote_after_zero_runs`（默认 6）次零产出，`plan` 会在**精简日**自动把它剔除并在日报里说明；**全量日不降频**，它仍会被跑到，所以降频是可自愈的，不会永久失明。用户说"恢复 XX 路"就把该车道的 `zero_streak` 归零；用户说"别再跑 XX 了"就把 lane id 写进 `config.discovery.disabled_lanes`。

这套统计的意义是：砍成本这件事有据可查。如果哪天召回明显变差，先看 yield-report，而不是凭感觉加路数。

## 明确降级 / 不作为每日默认来源

**BOSS直聘、拉勾** — 需要登录态 + CDP 才能稳定访问，反爬和账号风险较高。只有当某次运行所有车道都没有结果时，才考虑作为补充手段临时启用，不写入常规流程。

## 兜底原则

某个来源当天打不开、或没有相关结果，对应子 agent 应如实返回空数组，**不要**反复重试同一种访问方式去"确认"是否真的没有。orchestrator 不应因为单一来源当天失败/为空就中断整体流程，其余来源的结果照常合并处理。
