# 简历导入与求职画像

本文档定义：简历文件怎么收、存到哪、画像 `resumes/profile.json` 长什么样、初始化四问如何用画像预填。执行侧入口在 SKILL.md 第 0 步 / 第 1 步。

## 接收格式与提取途径

| 格式 | 提取途径 |
|---|---|
| PDF / PNG / JPG | 环境能直接读文件就直接读（Claude Code 的 Read 工具原生支持 PDF 和图片）；读不了 → `python3 $SKILL_DIR/scripts/extract_text.py --file <路径>` |
| MD / TXT | 直接读 |
| DOCX | 有 pandoc 就 `pandoc <文件> -t plain`；否则 `python3 $SKILL_DIR/scripts/extract_text.py --file <路径>` |
| 都失败 | 请用户把简历导出为 PDF 或 TXT 再发一次 |

**原件一律先存档再解析**：`python3 $SKILL_DIR/scripts/resume_store.py import-original --resumes $SKILL_DIR/resumes --file <用户给的文件>`，命令会打印存档后的相对路径（如 `originals/20260724-简历.pdf`），注册基底版本时把它填进 `--original`。

## 基底版本落档流程（初始化 0.1 / 老用户补传共用）

1. `import-original` 存原件。
2. 提取纯文本，写入 `$SKILL_DIR/resumes/versions/<YYYYMMDD>-base/resume.txt`。
3. 依据文本生成 `resumes/profile.json`（schema 见下）。
4. 注册并设为活跃基底：

```
python3 $SKILL_DIR/scripts/resume_store.py register --resumes $SKILL_DIR/resumes \
  --id <YYYYMMDD>-base --kind base --label "原始简历（导入）" \
  --original <import-original 打印的相对路径> \
  --txt versions/<YYYYMMDD>-base/resume.txt \
  --tags "<从画像归纳的3-6个标签，逗号分隔>" --set-active
```

## profile.json schema（存 `resumes/profile.json`，由 AI 生成）

```json
{
  "schema_version": 1,
  "generated_from": "20260724-base",
  "generated_at": "2026-07-24T09:00:00+08:00",
  "name_masked": "叶同学",
  "education": [ { "school": "...", "degree": "硕士", "major": "...", "start": "2024-09", "end": "2027-06" } ],
  "grad_year": "2027",
  "skills": { "hard": ["Python", "SQL"], "tools": ["Excel", "扣子"], "certificates": ["CPA在考"], "languages": ["英语六级"] },
  "experiences": [ { "org": "...", "role": "...", "period": "...", "keywords": ["审计"], "summary": "一句话" } ],
  "projects": [ { "org": "...", "role": "...", "period": "...", "keywords": [], "summary": "..." } ],
  "intent": { "directions": ["财务", "数据分析"], "cities_preferred": [], "notes": "" },
  "match_keywords": ["Python", "SQL", "审计", "财务", "数据分析"],
  "profile_summary": "两三句话画像，专供发现层子 agent prompt 注入，不含任何个人身份信息"
}
```

字段用途：`match_keywords` 供 `match_state.py pending` 算快评分（挑 8-15 个最能代表求职者竞争力和方向的词）；`profile_summary` 注入发现层 6 路子 agent 的 prompt；其余供深评打分时作证据。

## 隐私红线

profile.json 以及一切注入子 agent prompt 的内容**不得包含**：真实全名（用"X同学"式脱敏）、手机号、邮箱、照片、家庭住址。联系方式只存在于 `resumes/` 目录下的简历文件本身，永远不进 prompt。

## 初始化四问预填规则（v1"从零问"→ v2"AI 预填、用户确认"）

| 问题 | 预填推导 |
|---|---|
| 目标届别 | `education` 里最晚的 `end` 年份，格式"YYYY届"；无教育信息 → 退回 v1 原版直接问 |
| 岗位方向 | 从 `skills.hard` + `experiences[].keywords` 归纳 1-2 个方向建议。通用映射示例（方法示范，不写死行业）：审计/财报/CPA→财务；Python+SQL+建模→数据分析；前端/React→技术-前端；Java/Go/后端→技术-后端；新媒体/投放→市场营销；招聘/HRBP→人力资源；采购/物流→供应链；PRD/原型→产品经理 |
| 要不要看实习 | `int(grad_year) - 当前年份 >= 2` → 建议"也看实习"；否则建议"只看正式校招" |
| 招聘季节 | 当前月份 7-12 月 → "{当前年}秋招"（`season_end_date` = 次年 2 月末）；1-2 月 → "{上一年}秋招"（end = 当年 2 月末）；3-6 月 → "{当前年}春招"（end = 当年 7 月末） |

提问方式：有提问工具时每问的**第一个选项 = 预填答案**，标注"（从简历推断）"；没有提问工具就把四条预填值列出来，请用户逐条确认或纠正。确认后按 v1 逻辑归纳 `job_filter` 关键词写 config。

## watchlist 生成规则

初始化最后一步：按确认后的方向，生成 30-50 家"该方向常开校招"的公司名写入 `config.json` 的 `discovery.company_watchlist`（覆盖国企/民企/外企、头部与腰部），展示给用户并说明可随时增删（"帮我把XX加进监控名单"）。

## profile 刷新时机

- 初始化导入后立即生成。
- `register --set-active` 更换活跃基底后**必须**重新生成（画像跟着总简历走）。
- 注册 tailored 定制版**不**自动改 `active_base`——active_base 是"总简历"，日常深评统一对它打分；定制版只服务对应岗位的投递。

## 老用户补传（onboarded 但档案为空）

- **交互式会话**：提议补传（"把简历文件发我，我来建档并开启匹配评分"），拿到后走上面的落档流程再回到主管线。
- 用户说"不用了/不想传" → 把 config 的 `resume.enabled` 置 `false`，以后不再提。
- 用户说"以后再说" → 本次跳过深评，下次交互式运行再提一次。
- **无人值守**：跳过深评，日报会自动带"尚未导入简历"提示行（digest.py 处理，无需额外操作）。
