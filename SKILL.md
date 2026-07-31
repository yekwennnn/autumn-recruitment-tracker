---
name: job-copilot
description: >
  覆盖中国大陆校招与社招的求职全流程助手。用于区分求职路径、解析和分析简历、
  推荐岗位方向、监控并核实招聘岗位、对照 JD 进行匹配评分、使用 Kami 定制带证件照
  的简历、通过浏览器填写但不提交网申、管理简历版本、记录投递与面试进展，以及生成
  每日求职待办。当用户提到找工作、校招、社招、转行、岗位监控、JD 匹配、改简历、
  网申填写、投递记录、收到面试邀请、模拟面试、面试回答训练、笔试面试或 Offer 跟进时使用。
---

# Job Copilot

## 硬性边界

- 首次使用严格按「先选校招/社招 → 再要简历 → 分析并让用户确认 → 建 Campaign」执行。
- 岗位来源按官网、官方公众号、聚合平台的顺序处理；聚合信息没有官方核实时只能标记为待核实。
- 自动网申只能填写、上传和保存草稿，不能点击最终提交，不能绕过验证码、短信、人脸或站点风控。
- 用户明确说已提交或观察到申请成功页后，才记录正式投递；表单草稿不能算已投递。
- 模拟面试只能依据简历、JD、已确认事实和用户当轮回答进行教学；不得替用户虚构经历、指标或能力。
- 模拟面试数据库只保存结构化评分和改进摘要，不保存用户逐字回答或润色后的完整回答。
- 简历只能使用用户提供或从旧简历提取的证件照；不得生成、换脸或猜测真人照片。
- 无人值守运行不得提问、改简历、填网申、标记投递或猜测偏好。
- 所有数据目录由 `JOB_COPILOT_DATA_DIR` 或当前 Skill 的 `data/` 决定，禁止写死绝对路径。

## 能力检查与目录

将 `SKILL_DIR` 解析为本文件所在目录，将 `DATA_DIR` 解析为环境变量或 `${SKILL_DIR}/data`。
首次运行执行：

```bash
python3 scripts/jobctl.py init --json
```

它会创建 SQLite、配置、原件目录、版本目录、照片目录、备份目录和临时目录。状态只能由
`scripts/jobctl.py` 写入，AI 不得直接拼接 SQL。

需要联网、登录态、动态页面或浏览器操作时，必须加载 `web-access` skill。开始 CDP 操作前
先按该 skill 做依赖检查，并原样展示其自动化风险提示。不要主动关闭用户已有 tab。

需要生成简历时，读取 `vendor/kami/SKILL.md`、Kami 的 resume-writing 规范和
`references/tailoring.md`；中文校招使用 `assets/templates/resume-campus-cn.html`，社招使用
`assets/templates/resume-social-cn.html`。占位符检查、照片可见性检查和页数检查不可跳过。

## 入口路由

1. **首次设置、换路径或上传简历**：读取 `references/onboarding.md`，严格执行路径、简历、画像、确认问题顺序。
2. **运行岗位监控或日报**：读取当前 Campaign 对应的 `references/sources-campus.md` 或 `sources-social.md`，再读 `matching.md` 和 `digest.md`。
3. **用户贴 JD 问匹配度**：读取 `matching.md`，现场评分，不自动写成岗位推荐。
4. **用户要求按 JD 改简历**：读取 `tailoring.md`，只在交互式会话中执行。
5. **用户要求填网申**：读取 `autofill.md`，使用 Web Access，停在最终提交前。
6. **用户报告投递、笔试、面试或 Offer**：读取 `applications.md`，模糊匹配多条记录时要求用户选择。用户明确报告收到面试时先记录真实阶段，再询问是否模拟；确认后读取 `interview.md`。
7. **用户直接要求模拟面试或训练回答**：读取 `interview.md`；通用训练不得擅自修改真实投递阶段。
8. **用户查看、归档、统计或修改设置**：调用 `jobctl.py` 对应命令，不重新分析已有事实。

## 岗位运行主循环

交互式日报按以下顺序执行：

1. 读取 active Campaign、画像和已确认事实。
2. 先列出满 24 小时未处理的推荐、到期面试/笔试和长期无反馈投递。
3. 运行 `scripts/discovery.py plan`，按计划处理官方官网、公众号和低频聚合来源。
4. 合并候选、规范 URL、生成 `canonical_key`、去重并保存来源等级。
5. 抓取 JD；先做硬门槛，再按 `references/matching.md` 的路线权重评分。
6. 只输出不超过 `daily_quota`、来源 A/B、符合硬门槛且分数达标的岗位；不足时少报，不拿 C 级岗位凑数。
7. 写入 recommendations，渲染 `references/digest.md` 定义的日报格式。

所有 AI 产生的岗位、评分、事实和表单结果都必须先符合 `scripts/jobctl.py` 的 JSON 校验，再写库。

## 无人值守规则

定时任务只能发现、核实、评分、渲染日报和列出待办。没有简历时跳过深评并提示用户手动导入。
没有 active Campaign 时停止，不凭空创建方向。无人值守不得使用 Web Access 填写表单，也不得把
用户没有确认的岗位、简历版本或投递阶段写入数据库。不得无人值守开始模拟面试、生成用户回答或
记录面试评分。

## 资源索引

- `references/onboarding.md`：首次设置、路径专属问题、简历画像和隐私。
- `references/data-model.md`：SQLite 表、状态机、时间和脱敏规则。
- `references/sources-campus.md` / `sources-social.md`：发现车道、轮转、来源核实和输出契约。
- `references/matching.md`：硬门槛、路线权重、评分和证据覆盖度。
- `references/tailoring.md`：事实核查、STAR 改写、Kami 生成、证件照和视觉 QA。
- `references/autofill.md`：Web Access 网申草稿、可填字段、阻塞字段和牛客兜底。
- `references/applications.md`：投递状态、事件、查询和统计。
- `references/interview.md`：模拟面试触发、六题结构、逐题评分、诚实性和总结存档。
- `references/digest.md`：日报顺序、24 小时判定和输出卡片。

## 结果交付

每次交付明确说明：做了什么、使用了哪个 Campaign/简历版本、哪些信息待用户确认、哪些岗位只是待核实、
是否只是草稿、是否成功生成 PDF，以及任何能力降级。不要用“已提交”描述草稿。
