# 校招岗位发现

## 车道

```text
campus-official-launch       每天，官方秋招/春招启动公告
campus-official-watchlist    每天，意向公司官网轮询
campus-wechat-launch         每天，官方招聘公众号启动信息
campus-wechat-watchlist      每天，公司池公众号轮询
campus-aggregator-newcompany 每周，聚合名单发现新公司后回官网核实
campus-nowcoder               每周，牛客校招板块补漏
campus-intern                仅用户允许实习时每周运行
```

首次运行全量；之后官方来源每天，聚合来源每周。优先批次公司，不要重复输出已知公司已有的同一岗位。

## 来源等级

- A：官方岗位详情页或官方入口跳转到的 ATS 详情页。
- B：官方公众号/公告明确发布，且投递入口可确认。
- C：聚合平台或讨论区，尚未回官方核实。

A/B 才可进入正式推荐；C 只放“待核实”。

## 单条候选 JSON

输出只能是 JSON 数组，字段为：`company`、`title`、`city`、`route`、`employment_type`、
`source_platform`、`source_url`、`official_url`、`application_url`、`source_tier`、`jd_text`、
`deadline`、`official_job_id`。没有截止日期填 `null`，不能推测。

来源打不开时返回空数组，不要反复重试。使用 Web Access 时不得把个人信息发送给检索任务。
