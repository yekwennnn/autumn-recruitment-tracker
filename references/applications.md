# 投递追踪

填写草稿不等于投递。只有用户明确说已提交，或后续看到明确成功确认页/申请编号，才能执行：

```bash
python3 scripts/jobctl.py application mark-submitted \
  --posting-id <岗位ID> --resume-version-id <版本ID> --channel 官网 --json
```

没有显式提供 `--next-action-at` 时，系统按 Campaign 时区安排投递日期后第 3 个自然日的日报状态检查。
例如 7 月 31 日投递，日报时间为 09:00，则默认在 8 月 3 日 09:00 到期。用户明确指定的时间优先。
`draft_filled` 和 `ready_for_review` 不会建立该提醒。

更新阶段：

```bash
python3 scripts/jobctl.py application stage \
  --id <投递ID或唯一公司/岗位关键词> --stage 一面 --json
```

模糊匹配多条时停下来让用户选择。每次阶段变化写 `application_events`。

## 状态检查

日报提醒后，按用户反馈执行：

```bash
# 已查看，暂无更新：从检查日顺延 3 个自然日
python3 scripts/jobctl.py application check-status \
  --id <投递ID或唯一公司/岗位关键词> --result no-update --json

# 状态已更新；笔试和面试存在明确时间时同时传 next-action-at
python3 scripts/jobctl.py application check-status \
  --id <投递ID> --result updated --stage 一面 \
  --next-action-at <ISO时间> --json

# 停止状态提醒，但保留投递记录
python3 scripts/jobctl.py application check-status \
  --id <投递ID> --result stop --json
```

同一关键词命中多条时只返回 `candidates`，让用户改用明确的投递 ID。用户报告拒绝、放弃、过期或归档时，
进入终止态并自动清除 `next_action_at`。用户忽略提醒时不改数据、不归档，下一份日报继续展示。

查询：

```bash
python3 scripts/jobctl.py application list --open-only
python3 scripts/jobctl.py application stats
```

样本少于 10 条时提示统计不稳定。跟用户复述时区分：岗位推荐、网申草稿、已投递、筛选中、面试和 Offer。

用户明确报告收到面试时，先按上述规则确认并更新对应投递记录，再询问是否进行模拟面试；用户同意后读取
`references/interview.md`。仅询问通用面试技巧时不要更新真实投递阶段。
