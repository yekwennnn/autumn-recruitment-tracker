# 简历导入、简历分析与求职画像

本文档定义：简历文件怎么收、存到哪、**怎么分析并给出岗位方向推荐**、画像 `resumes/profile.json` 长什么样、初始化提问如何用分析结论预填。执行侧入口在 SKILL.md 第 0 步 / 第 1 步。

## 顺序红线：简历在前，提问在后

初始化是**严格串行**的三段，不允许合并、不允许并行、不允许"顺便一起问"：

```
0.1 只要简历   →   0.2 分析简历并推荐方向   →   0.3 才问那四个基础问题
```

**在简历文件拿到手并成功提取出文本之前，不得向用户提出任何配置问题**——不问届别、不问方向、不问要不要实习、不问招不招人的季节，一个都不问。第一条消息只做一件事：请用户把简历发过来。

理由很直接：这四个问题的答案基本都能从简历里读出来。先问，用户要凭空回忆着答一遍；后问，用户只需要点"对"。顺序颠倒会让整个初始化体验退回到没有简历的水平。

例外只有一个：用户明确拒绝提供简历（"不想传""没有电子版"），这时把 config 的 `resume.enabled` 置 `false`，改用从零四问（不预填），并说明匹配评分和改简历功能会关闭。

如果用户的第一条消息里就带了简历文件，直接用，不要再要一次。

## 接收格式与提取途径

| 格式 | 提取途径 |
|---|---|
| PDF / PNG / JPG | 环境能直接读文件就直接读（Claude Code 的 Read 工具原生支持 PDF 和图片）；读不了 → `python3 $SKILL_DIR/scripts/extract_text.py --file <路径>` |
| MD / TXT | 直接读 |
| DOCX | 有 pandoc 就 `pandoc <文件> -t plain`；否则 `python3 $SKILL_DIR/scripts/extract_text.py --file <路径>` |
| 都失败 | 请用户把简历导出为 PDF 或 TXT 再发一次（这时仍然停在 0.1，不要跳到 0.3 去问问题） |

**原件一律先存档再解析**：`python3 $SKILL_DIR/scripts/resume_store.py import-original --resumes $SKILL_DIR/resumes --file <用户给的文件>`，命令会打印存档后的相对路径（如 `originals/20260724-简历.pdf`），注册基底版本时把它填进 `--original`。

## 基底版本落档流程（初始化 0.1 / 老用户补传共用）

1. `import-original` 存原件。
2. 提取纯文本，写入 `$SKILL_DIR/resumes/versions/<YYYYMMDD>-base/resume.txt`。
3. 做 0.2 的简历分析，据此生成 `resumes/profile.json`（schema 见下）。
4. 注册并设为活跃基底：

```
python3 $SKILL_DIR/scripts/resume_store.py register --resumes $SKILL_DIR/resumes \
  --id <YYYYMMDD>-base --kind base --label "原始简历（导入）" \
  --original <import-original 打印的相对路径> \
  --txt versions/<YYYYMMDD>-base/resume.txt \
  --tags "<从画像归纳的3-6个标签，逗号分隔>" --set-active
```

## 0.2 简历分析与方向推荐

拿到简历文本后，**先给用户看一份分析**，再进入提问。这一步是用户对"这个工具到底读懂了我没有"的第一次也是唯一一次验证机会，写得含糊等于白做。

输出四块，直接讲给用户听（不是内部推理，是要展示的内容）：

### ① 画像速览
学历层次 / 学校 / 专业 / 预计毕业时间、核心技能、经历主线（一句话概括这份简历讲的是个什么故事）。控制在 4-6 行。

### ② 优势（3 条）
每条格式：**结论 —— 证据**。证据必须是简历里实际写着的内容（可以概括，不能虚构）。

> 好：`量化分析能力可直接迁移 —— 简历里"用 Python 清洗 3 万条交易数据并出月度对账表"是完整的数据处理链路`
> 坏：`具备较强的数据分析能力和学习能力`（没有证据，等于没说）

### ③ 短板（2-3 条）
同样要有依据，但依据可以是"简历里找不到"。要说清楚这个短板会在什么场景下卡住你。

> 好：`没有金融行业实习 —— 简历三段经历都在校内，券商/银行的 JD 普遍写"有相关实习优先"，这一项会在简历筛就减分`
> 坏：`经验略显不足`

**红线：分析只能基于简历里的内容。** 不确定的地方直接写"简历里没写，需要你补充"，不要用"应该""大概""通常来说"往下推。这条红线和改简历的实事求是原则是同一条。

### ④ 推荐 2-3 个岗位方向
每个方向给全这五项：

| 项 | 说明 |
|---|---|
| 方向名 | 用招聘市场上真实存在的叫法（"财务分析"而不是"和钱有关的岗位"） |
| 契合度 | 高 / 中，并说明凭什么 |
| 推荐理由 | 引用简历里的具体证据，至少一条 |
| 典型岗位名 | 2-4 个该方向常见的校招岗位标题，用于后面归纳 `positive_keywords` |
| 要补什么 | 想投这个方向，短板里哪一条最该先补 |

推荐要有取舍：**第一个是主推方向，后面的是备选**，并说清楚为什么这个排第一。如果简历指向非常集中，推 2 个就够，不要为了凑数硬推第三个。如果简历信息太少（例如只有一页学历没有经历），如实说"能判断的依据不足"，给出你能给的，并在 0.3 里请用户自己定方向。

分析结论要落进 `profile.json` 的 `strengths` / `gaps` / `recommended_directions` 字段——后面深评打分、改简历的 W3 诚实性核查都会复用它，不用重新分析一遍。

## profile.json schema（存 `resumes/profile.json`，由 AI 生成）

```json
{
  "schema_version": 2,
  "generated_from": "20260724-base",
  "generated_at": "2026-07-24T09:00:00+08:00",
  "name_masked": "叶同学",
  "education": [ { "school": "...", "degree": "硕士", "major": "...", "start": "2024-09", "end": "2027-06" } ],
  "grad_year": "2027",
  "skills": { "hard": ["Python", "SQL"], "tools": ["Excel", "扣子"], "certificates": ["CPA在考"], "languages": ["英语六级"] },
  "experiences": [ { "org": "...", "role": "...", "period": "...", "keywords": ["审计"], "summary": "一句话" } ],
  "projects": [ { "org": "...", "role": "...", "period": "...", "keywords": [], "summary": "..." } ],
  "strengths": [ { "claim": "量化分析能力可直接迁移", "evidence": "简历中'用Python清洗3万条交易数据并出月度对账表'" } ],
  "gaps": [ { "claim": "没有金融行业实习", "evidence": "三段经历均在校内", "impact": "券商/银行JD普遍要求相关实习，简历筛会减分" } ],
  "recommended_directions": [
    { "name": "财务分析", "fit": "高", "reason": "CPA在考+Excel建模+对账经验三项直接对口",
      "typical_titles": ["财务管培生", "财务分析岗", "FP&A"], "to_improve": "补一段券商或事务所实习" }
  ],
  "intent": { "directions": ["财务", "数据分析"], "cities_preferred": [], "notes": "" },
  "match_keywords": ["Python", "SQL", "审计", "财务", "数据分析"],
  "profile_summary": "两三句话画像，专供发现层子 agent prompt 注入，不含任何个人身份信息"
}
```

字段用途：`match_keywords` 供 `match_state.py pending` 算快评分（挑 8-15 个最能代表求职者竞争力和方向的词）；`profile_summary` 注入发现层子 agent 的 prompt；`strengths`/`gaps` 供深评打分和改简历时作证据；`recommended_directions` 供 0.3 的方向提问和后续"要不要换方向"的对话；其余供深评打分时作证据。

`intent.directions` 是**用户确认后**的最终方向，可能和 `recommended_directions` 不同——用户有权不听推荐，以 `intent` 为准。

## 隐私红线

profile.json 以及一切注入子 agent prompt 的内容**不得包含**：真实全名（用"X同学"式脱敏）、手机号、邮箱、照片、家庭住址。联系方式只存在于 `resumes/` 目录下的简历文件本身，永远不进 prompt。

## 0.3 四问预填规则

四个问题全部带着答案去问，用户只需确认或纠正：

| 问题 | 预填推导 |
|---|---|
| 目标届别 | `education` 里最晚的 `end` 年份，格式"YYYY届"；无教育信息 → 直接问 |
| 岗位方向 | **直接用 0.2 的 `recommended_directions`**：主推方向作第一选项，备选方向依次排后，最后留一个"都不是，我想投别的" |
| 要不要看实习 | `int(grad_year) - 当前年份 >= 2` → 建议"也看实习"；否则建议"只看正式校招" |
| 招聘季节 | 当前月份 7-12 月 → "{当前年}秋招"（`season_end_date` = 次年 2 月末）；1-2 月 → "{上一年}秋招"（end = 当年 2 月末）；3-6 月 → "{当前年}春招"（end = 当年 7 月末） |

提问方式：有提问工具时每问的**第一个选项 = 预填答案**，方向那问的选项直接来自 0.2 的推荐（选项描述里带上"契合度"和一句推荐理由）；没有提问工具就把四条预填值列出来，请用户逐条确认或纠正。

确认后归纳 `job_filter` 关键词写 config：`positive_keywords` 主要来自确认方向的 `typical_titles`，`fuzzy_keywords` 放"管理培训生""储备干部"这类不写明方向的通用叫法，`negative_keywords` 放明显不想要的方向词。

## watchlist 生成规则

初始化最后一步：按确认后的方向，生成 30-50 家"该方向常开校招"的公司名写入 `config.json` 的 `discovery.company_watchlist`（覆盖国企/民企/外企、头部与腰部），展示给用户并说明可随时增删（"帮我把XX加进监控名单"）。

## profile 刷新时机

- 初始化导入后立即生成（含 0.2 的分析结论）。
- `register --set-active` 更换活跃基底后**必须**重新生成，包括重做一次 0.2 分析（画像跟着总简历走）。
- 注册 tailored 定制版**不**自动改 `active_base`——active_base 是"总简历"，日常深评统一对它打分；定制版只服务对应岗位的投递。

## 老用户补传（onboarded 但档案为空）

- **交互式会话**：提议补传（"把简历文件发我，我来建档、做一次简历分析并开启匹配评分"），拿到后走上面的落档流程（含 0.2 分析）再回到主管线。
- 用户说"不用了/不想传" → 把 config 的 `resume.enabled` 置 `false`，以后不再提。
- 用户说"以后再说" → 本次跳过深评，下次交互式运行再提一次。
- **无人值守**：跳过深评，日报会自动带"尚未导入简历"提示行（digest.py 处理，无需额外操作）。

## 用户想重看分析 / 换方向

- "我的简历分析呢" / "我优势是什么" → 读 `profile.json` 的 `strengths`/`gaps`/`recommended_directions` 复述，不要重新分析（除非简历换过）。
- "我想换个方向投" → 从 `recommended_directions` 里的备选方向挑，或按用户说的新方向重新归纳 `job_filter` 关键词 + 重生成 watchlist，写回 config 并复述。
