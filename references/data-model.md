# 数据模型和状态机

当前数据库 schema 版本为 2。任何旧版本迁移前必须先备份已有数据库。

## 数据目录

默认 `data/`，也可用 `JOB_COPILOT_DATA_DIR` 覆盖。目录权限尽量为 0700，数据库和配置文件尽量为 0600。
简历文件不写入 SQLite BLOB，数据库只记录相对路径、哈希和关联 ID。

## 时间

- 所有时间存带时区 ISO 8601。
- 默认时区 `Asia/Shanghai`。
- 截止日期只保存页面明确写出的日期；没有写就用 `null`。
- 岗位推荐后 `decision_due_at = recommended_at + 24 小时`。

## 岗位状态

```text
active → archived
active → expired
```

用户说“删除岗位”只把岗位和推荐软归档，不能物理删除。归档岗位不再推荐，但仍用于去重和统计。

## 推荐状态

```text
pending → preparing → applied
pending → snoozed → preparing
pending → archived
pending → expired
```

以下动作会更新 `last_progress_at` 并重新计算待办时间：生成定制简历、开始填表、保存网申草稿、用户选择保留明天、正式投递。

## 表单状态

```text
started → blocked
started → draft_filled → ready_for_review
ready_for_review → submission_confirmed
started → abandoned
```

`draft_filled` 和 `ready_for_review` 都不是正式投递。

## 投递阶段

```text
已投递 → 筛选中 → 在线测评/笔试 → HR沟通 → 一面 → 二面 → 终面 → Offer
```

终止态：`拒绝`、`放弃`、`过期`、`归档`。每次变化新增 `application_events`，不能覆盖历史。

## 投递后状态检查

正式投递且没有显式待办时：

```text
next_action_at = 投递本地日期 + 3 个自然日，并使用 Campaign.digest_time
```

`status_checked_no_update` 会从检查时间重新安排 3 个自然日；`followup_stopped` 清空待办但不关闭投递；
终止阶段自动清空待办。草稿状态不创建投递和提醒。

## 模拟面试状态

```text
started → in_progress → completed
started/in_progress → abandoned
```

`interview_sessions` 关联 Profile，可选关联 application、posting 和 resume version。它只保存题型计划、逐题
维度分数、问题标签、改进摘要和最终训练计划，不保存用户逐字回答或完整润色答案。完成与真实投递关联的模拟
面试时，新增 `mock_interview_completed` application event，但不改变真实投递阶段。

## 24 小时待办查询

只列：

```text
recommendation.status ∈ {pending, preparing, snoozed}
recommendation.decision_due_at <= now
posting.status = active
没有正式 application
```

用户不回答时不自动删除；下一日报继续列出。
