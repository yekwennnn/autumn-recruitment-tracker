# 模拟面试

## 触发与真实进展

当用户说“接到/收到面试”“约面”“进面”“通知一面、二面、终面”“HR 面、业务面、技术面”等，
先把它当作真实投递进展处理：

1. 用 `application list` 查找记录。
2. 同一公司或关键词命中多条时列出候选，让用户选择；禁止默认更新第一条。
3. 用户已明确公司、岗位和轮次时，用 `application stage` 记录真实阶段。
4. 询问：“要不要现在针对这个岗位进行一轮模拟面试？”
5. 用户确认后再创建模拟面试会话。

用户只问通用面试技巧、没有报告真实邀请时，不修改任何投递阶段。

## 开始前准备

优先从选中的 application 读取：

- 公司、岗位、JD 和求职路径。
- 投递所用简历版本。
- Profile 和 `confirmed_facts` 中已确认经历。
- 当前面试轮次。

集中补问缺失的高价值信息：面试轮次、HR/业务/专业面类型、已知面试形式和面试时间。JD 缺失时可以训练，
但必须明确说“以下问题基于岗位名称和简历，针对性低于完整 JD 场景”，不得补造招聘要求。

通过真实投递开始：

```bash
python3 scripts/jobctl.py interview start \
  --application-id <投递ID> \
  --round-label 一面 \
  --focus 产品 \
  --json
```

没有投递记录时，允许建立独立训练：

```bash
python3 scripts/jobctl.py interview start \
  --profile-id <Profile ID> \
  --company <公司> \
  --title <岗位> \
  --route social \
  --round-label 业务面 \
  --focus 产品 \
  --json
```

默认 `question-count=6`、`mode=coached`。数据库中的 `plan` 只保存题型和训练重点，不保存用户回答。

## 六题结构

一次只问一题，等待用户回答后再点评。默认题型为：

1. 自我介绍和求职动机。
2. 简历经历深挖。
3. JD 核心能力验证。
4. 协作、冲突、失败或复盘。
5. 岗位场景题或业务案例。
6. 反问面试官和收尾表达。

按场景调整：

- 校招：强调项目、实习、学习能力、角色贡献和职业动机。
- 社招：强调成果、职责边界、指标、业务判断、取舍和岗位迁移。
- HR 面：强调动机、稳定性、职业规划、到岗时间；薪资等偏好必须先确认。
- 业务/专业面：强调方法、案例、数据、取舍和复盘。
- 终面：强调价值观、复杂决策、长期发展和高质量反问。

用户可说“重答”“跳过”“提前结束”或“再加一题”。新增题目后题号不得超过 20。

## 逐题评分与反馈

每题按以下上限评分，总分 100：

```text
relevance 回答相关性：25
evidence 事实与证据：25
structure 表达结构：20
role_fit 岗位契合度：20
clarity 简洁与清晰度：10
```

每次点评固定输出：

1. 本题总分和一句话结论。
2. 回答中最有效的内容。
3. 最大问题及其面试影响。
4. 推荐结构：STAR、PREP 或“结论—证据—结果”。
5. 基于已确认事实的润色示例。
6. 让用户选择重答一次或继续下一题。

点评后只记录分数、问题标签和简短改进摘要：

```bash
python3 scripts/jobctl.py interview progress \
  --id <会话ID> \
  --question-index 1 \
  --relevance 20 \
  --evidence 18 \
  --structure 16 \
  --role-fit 15 \
  --clarity 8 \
  --issue-tags "缺少量化结果,结论偏后" \
  --improvement-summary "先给岗位相关结论，再用一个已确认项目说明行动与结果" \
  --json
```

不要把用户原话、完整润色答案、聊天记录或 transcript 传入 CLI。用户在回答中补充了可复用的新事实时，
先复述并确认，再立即用 `fact add` 写入 `confirmed_facts`。

## 诚实性边界

- 只使用简历、JD、`confirmed_facts` 和用户本轮明确提供的信息。
- 不得虚构项目、职责、指标、技术熟练度、团队规模或管理经验。
- 不得把“接触过”改成“熟练”，不得把 AI 辅助改成独立完成。
- 缺少数字时写“这里需要补充真实数据”，不要生成看似合理的数字。
- 用户确认没有某项能力时，把它标为 capability gap，并给学习或应答策略；不要写入示例回答。
- 润色只改善结构、相关性和表达，不改变事实含义。

## 完成与总结

六题完成或用户提前结束时，输出：

- 综合分和五个维度平均分。
- 表现最好的 3 项。
- 优先改进的 2–3 项。
- 可能出现的追问题。
- 推荐反问题目。
- 下一轮训练计划。
- 面试前快速复习要点。

只把结构化总结写入数据库：

```bash
python3 scripts/jobctl.py interview complete \
  --id <会话ID> \
  --strengths-json '["经历证据具体","能解释业务目标"]' \
  --gaps-json '["结论出现过晚","结果缺少真实量化信息"]' \
  --actions-json '["用90秒版本重练自我介绍","补齐项目真实指标"]' \
  --followups-json '["你在项目中的职责边界是什么？"]' \
  --reverse-questions-json '["该岗位入职三个月的成功标准是什么？"]' \
  --review-points-json '["先结论后证据","不知道的数据不猜"]' \
  --json
```

未显式提供综合分时，CLI 使用已记录题目的平均分。中途终止：

```bash
python3 scripts/jobctl.py interview abandon --id <会话ID> --reason <原因> --json
```

查询：

```bash
python3 scripts/jobctl.py interview list --profile-id <Profile ID> --json
python3 scripts/jobctl.py interview show --id <会话ID> --json
```

`show` 只展示题型、评分和总结；数据库、导出和日志都不得出现逐字回答。
