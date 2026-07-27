# 投递追踪

监控发现岗位、深评给分、改简历——这三步之后还有最长的一段：投出去之后发生了什么。没有这一段，"越用越懂你"是断的：深评分数是自评，只有**真实的过筛/被拒**才是外部信号。

数据存 `state/applications.json`，唯一写方是 `scripts/apply.py`。

## 什么时候记

- **改完简历、用户说要投** → 立刻 `mark`（改简历流程 W7 之后的规定动作）。
- 用户说"我投了XX""刚网申了XX" → `mark`。
- 用户说"XX让我去笔试了""XX一面过了""XX挂了" → `stage`。
- 用户问"我投了哪些""进展怎么样" → `list` / `stats`。
- 每次监控运行渲染日报时 → 自动带出"待跟进"区块，不需要用户开口。

**无人值守运行只读不写**：可以渲染待跟进提醒，但不得替用户标记任何投递状态或阶段。

## 记一次投递

```
python3 $SKILL_DIR/scripts/apply.py mark \
  --applications $SKILL_DIR/state/applications.json \
  --state $SKILL_DIR/state/seen_postings.json \
  --posting-id <岗位id> --resume-version <简历版本id> --channel 官网
```

`--posting-id` 用监控库里的岗位 id，公司名、岗位名、截止日期会自动带过来。库外的岗位（用户自己在别处看到的）改用 `--company` + `--title`。

可选：`--date`（补记历史投递）、`--next-action YYYY-MM-DD`（约好的笔试/面试时间）、`--note`。

**`--resume-version` 尽量别省**。它是后面算"哪一版简历更能过筛"的唯一依据，省了就等于这次投递白投了统计价值。

网申填表流程（`webapply.md`，路由 E）在表单**真的提交成功之后**会自动来记这一笔，`--channel` 固定填 `官网网申`；库外的岗位把网申链接放进 `--note`。填了但停在提交前没投的，不记。

## 更新进展

```
python3 $SKILL_DIR/scripts/apply.py stage \
  --applications $SKILL_DIR/state/applications.json \
  --id <投递id或公司名关键字> --stage 一面 --next-action 2026-08-20
```

阶段取值（顺序即漏斗深度）：`已投递` → `简历通过` → `笔试` → `一面` → `二面` → `三面` → `HR面` → `offer`；终止态另有 `挂了`、`放弃`。

`--id` 支持传公司名/岗位名的关键字模糊匹配，匹配到多条会列出候选让你用准确 id 再来一次——**不要自己猜是哪一条**。

## 待跟进的判定

```
python3 $SKILL_DIR/scripts/apply.py followups \
  --applications $SKILL_DIR/state/applications.json --config $SKILL_DIR/config.json
```

两类：

- **待办到期** — `next_action_at` 已到或已过（笔试今天、面试昨天忘了记结果）。
- **投了没动静** — 还停在"已投递"且超过 `applications.followup_days`（默认 14 天）。超过 `applications.stale_days`（默认 30 天）的额外标注"疑似已挂，可以考虑放弃了"。

日报的"📮 投递待跟进"区块由 `digest.py` 直接读 applications.json 渲染（传 `--applications`），不需要单独调 followups。

## 战绩统计

```
python3 $SKILL_DIR/scripts/apply.py stats \
  --applications $SKILL_DIR/state/applications.json --by-version
```

输出总漏斗（投递数 / 过简历筛数 / 过筛率 / offer 数）和按简历版本拆分的过筛率。

**这个数字要老实用**：校招投递样本量通常只有几十，版本之间几个百分点的差距没有统计意义，脚本自己也会在多版本时打印这句提醒。它能回答的是"这一版明显不行"（投了 15 个 0 过筛），不是"A 版比 B 版好 3%"。

改简历时（`tailoring.md` W1 选基底）应该先看一眼这个统计：**过筛率明显偏低的版本不要再拿来当基底**。

## 与截止日期的关系

已投递的岗位不会再出现在日报的"⏰ 网申截止预警"里——投都投了，催没有意义。这个排除靠 `mark` 时带上 `--posting-id` 建立的关联，这也是能用 posting-id 就别用手填公司名的另一个理由。
