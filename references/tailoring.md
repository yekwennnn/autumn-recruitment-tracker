# 一键改简历（简历工坊 W1-W7）

本流程把三样东西串起来：`vendor/resume-jd-fit/SKILL.md`（六步定制法，直接 Read 当操作指引）、`vendor/kami/`（排版工具箱）、本仓库的档案与洞察脚本。**无人值守（定时任务）绝对禁止进入本流程**——诚实性核查必须有用户在场应答。

选基底（W1）之前先看一眼 `python3 $SKILL_DIR/scripts/apply.py stats --applications $SKILL_DIR/state/applications.json --by-version`：**过筛率明显偏低的版本不要再拿来当基底**。样本少的时候这个数字只能当参考，能说明问题的是"投了十几个一个没过"，不是几个百分点的差别。

## 入口

- (a) 监控日报输出后，用户选中某个高分岗位（选项按钮或回复编号）。
- (b) 用户任何时候贴 JD / 说"帮我改简历投XX"（走 SKILL.md 入口路由 B，不跑监控管线）。

## W1 取材

- 来自日报的岗位：直接用 state 里该岗位的 `match.jd_summary` / `jd_url`；需要更多细节时按 `references/matching.md` 的抓取契约现抓全文。
- 用户贴的 JD：直接用原文。

## W2 选基底

```
python3 $SKILL_DIR/scripts/resume_store.py pick-base --resumes $SKILL_DIR/resumes \
  --keywords "<jd_keywords 逗号串>"
```

向用户确认选中的基底版本后定稿。`score_before` = 该基底对本 JD 的匹配分：岗位在 state 里已有 `match.score` 就直接用；否则按 matching.md 量表现打一次。

## W3 差距分析与诚实性核查

1. 先跑 `python3 $SKILL_DIR/scripts/insights.py show --insights $SKILL_DIR/state/match_insights.json`——**`confirmed_facts` 里已沉淀的素材不要重复追问用户**，直接当作已核实证据用。
2. 然后执行 `vendor/resume-jd-fit/SKILL.md` 的 **Step 1（JD 差距分析）→ Step 2（诚实性核查）→ Step 3（保密脱敏）**，一步不跳。
3. Step 2 每问出一条新的真实素材，**立刻**沉淀：

```
python3 $SKILL_DIR/scripts/insights.py add-fact --insights $SKILL_DIR/state/match_insights.json \
  --claim "<一句话主张>" --detail "<具体做了什么/角色/产出>" --stage "demo|个人使用|已上线|其他"
```

## W4 改写

执行 resume-jd-fit 的 **Step 4**（复用现有简历结构原地改内容）。基底没有 HTML（例如初始导入的是 PDF）→ 起版模板按下表选，动笔前先读 `vendor/kami/CHEATSHEET.md` + `vendor/kami/references/resume-writing.md`。

| 场景 | 用哪个模板 |
|---|---|
| **中文校招简历（默认）** | `$SKILL_DIR/assets/templates/resume-campus-cn.html` |
| 英文简历 | `$SKILL_DIR/vendor/kami/assets/templates/resume-en.html` |
| 社招 / 有多年工作经历 | `$SKILL_DIR/vendor/kami/assets/templates/resume.html` |

> **默认必须用校招版，不要直接拿 kami 的 `resume.html`。**
>
> kami 原版是**社招**布局：教育背景排在最后一节，有"工作经历"而没有"实习经历"，还有"开源项目 & 独立开发者""AI 判断与行动""对外影响力"这些资深工程师专属章节。给应届生用会有两个后果：学历这个**校招第一筛选项**被埋到最底下；以及三个填不满的章节逼着人注水。
>
> 校招版的章节顺序是 **个人评价 → 教育背景 → 实习经历 → 项目经历 → 技能证书 → 荣誉奖项（可选）**，一页制。
>
> 它的**版式逐字节继承自 kami**（`<head>` 与整个 `<style>` 原样复制），只换了正文结构，所以视觉上和 kami 出品完全一致。改章节结构改 `assets/campus-body.html` 后重新生成：
>
> ```
> python3 $SKILL_DIR/scripts/make_campus_template.py
> ```
>
> **不要直接编辑 `assets/templates/resume-campus-cn.html`**，它是生成物，下次重新生成会被覆盖。

> `vendor/kami/SKILL.md` 是上游 V1.10.0 原文，本仓库只内嵌了简历所需子集（详见 `vendor/README.md`）。走到下面这些分支时**声明跳过**，不要去找文件：
> - **Step 0 品牌档案**（读 `~/.config/kami/brand.md`）——本流程不用品牌档案。
> - **diagrams / mermaid 路由**——`assets/diagrams/` 未内嵌，简历不出图表。
> - **简历以外的文档类型**（one-pager / portfolio / slides / letter / long-doc / landing-page / changelog / equity-report）与**韩文模板**——对应 `assets/templates/` 未内嵌。

> **STAR + 实事求是（每条 bullet 逐条过，不许跳）**
> - 每条经历/项目按 STAR 组织：Situation+Task 压成一句背景（什么场景要解决什么问题）；Action 突出**本人**动作并与 JD 关键词自然对齐；Result 单独写真实结果。与 kami `resume-writing.md` 的 Role/Action/Result 标准兼容（Role≈S/T），冲突时以 STAR 为准。
> - 三条红线：① Result 没有真实数字就写规模/状态（如"个人使用，未对外发布"），**禁止编造任何指标**；② 工具辅助查资料 ≠ 开发经验、demo ≠ 上线产品，措辞严格按 resume-jd-fit Step 2 的对照表；③ JD 要求而简历无证据的能力，宁可留白说明，不许硬凑（与 matching.md"无证据按缺失计"同一原则）。
> - 每条改动记入 meta.json 的 `changes[]`，交付时逐条向用户报告依据，保证每句话面试都能答上。

## W4.5 证件照

中文校招简历默认**贴证件照**（`resume-campus-cn.html` 的 header 右上角有照片位；kami 原模板没有，这是校招版新增）。

照片来源两条路，都用 `resume_store.py photo` 转成 base64 data URI：

```
# A. 用户直接给照片文件
python3 $SKILL_DIR/scripts/resume_store.py photo \
  --file <照片路径> --out $SKILL_DIR/state/tmp/photo.txt

# B. 用户没单独的照片，但旧简历 PDF 里有（抽第 1 页最大的那张图）
python3 $SKILL_DIR/scripts/resume_store.py photo \
  --from-pdf <旧简历.pdf> --out $SKILL_DIR/state/tmp/photo.txt
```

把 `photo.txt` 的内容整个填进模板的 `{{PHOTO_DATA_URI}}`。

规矩：

- **必须用 data URI，不能写文件路径。** 四件套要能整体挪走、`source.html` 双击就能看；写路径一挪就裂图。上一版就是栽在相对路径上。
- **走 B 路（从旧 PDF 抽）时要告诉用户照片是从哪份文件来的**，别默认他满意那张老照片；但也不要卡在这里等确认，先做完再说一句。
- 旧 PDF 里没有内嵌图片 → 脚本会明说，改走 A 路请用户提供，**不要自己找图或生成头像**。
- 照片编码后超过 800KB 脚本会警告。简历上只显示 17.5×24mm，先压到 500px 宽以内再转，PDF 会小很多。
- **用户明确说不要照片** → 删掉模板里整行 `<img class="photo">`，CSS 留着无害。

隐私：照片和简历原件一样只存在本机 `resumes/` 下（已 gitignore），**永远不进任何子 agent 的 prompt**。

## W5 渲染

1. `bash $SKILL_DIR/vendor/kami/scripts/ensure-fonts.sh` —— 失败**不阻断**（模板自带 CDN 与系统字体兜底链）。

2. **渲染前先查占位符**（kami V1.10.0 起提供，**这一步不可跳**）：

```
python3 $SKILL_DIR/vendor/kami/scripts/build.py --check-placeholders "$(cd $SKILL_DIR && pwd)/resumes/versions/<版本id>/source.html"
```

漏填的 `{{姓名}}`、`{{EMAIL}}` 之类会被逐个列出来。**报错就回去填，不许带着占位符往下走**——投出去一份写着 `{{姓名}}` 的简历是这个流程能造成的最严重事故。

> **必须传绝对路径。** `build.py` 对相对路径是按 **kami 自己的目录**解析的（`vendor/kami/scripts/checks.py` 里 `path = ROOT / path`），传相对路径会得到一句 `file not found`——那是路径找错了，不是文件真的没有，别据此以为检查通过了。

3. 渲染 PDF：

```
python3 -c "from weasyprint import HTML; HTML('<版本目录>/source.html', base_url='<版本目录>').write_pdf('<版本目录>/resume.pdf')"
```

4. **查 markdown 残留**（同样是 V1.10.0 起提供，同样必须传绝对路径）：

```
python3 $SKILL_DIR/vendor/kami/scripts/build.py --check-markdown "$(cd $SKILL_DIR && pwd)/resumes/versions/<版本id>/resume.pdf"
```

抓 `**加粗**`、反引号、`---` 这类漏进成稿的标记——AI 改写内容时很容易留下。

5. 用 pypdf 数页数；超过一页 → 按 resume-jd-fit **Step 5** 修（装了 pdfplumber 就量化测缺口再改；没装就按"压 dense 字号 → 削页边距 → 合并内容行"顺序改后重测页数）。同时按其 Bug 2 检查所有 CJK 标签列不换行。

> **量剩余空间要扣掉页边距。** `页高 - 最后一行 bottom` 量到的是**物理页边**，模板下页边距 11mm 不可用。真正可用空间 = 那个数 − 11mm。踩过一次：显示"剩 23.8mm"却仍然溢出，因为实际只剩 12.8mm，而那一节整块需要 18mm（section 是 `break-inside: avoid`，装不下就整块跳页）。
>
> 先用 kami 自带的 `resume--dense`（给 `<body>` 加 `class="resume--dense"`）压一档，不够再动内容。**加 class 时注意**：样式表注释里有一句 `add class="resume--dense" to <body>`，用正则找 `<body>` 会命中那句注释，必须从 `</style>` 之后开始找真标签。

> **页数：我们要一页，kami 要两页——以我们为准。**
>
> kami 的 resume 模板是按**两页**设计的（`vendor/kami/references/resume-writing.md` 的 "Two-page balance" 一节写着"Exactly 2 pages"、每页填充 83-95%），面向的是资深工程师的作品集式简历。**中文校招简历是一页制**，HR 一天筛几百份，第二页基本不会看。
>
> 所以：读 kami 的 resume-writing.md 取排版手法（字号、行高、分栏的对应表很有用），但**页数标准一律以本流程的"一页"为准**，不要因为 kami 说两页就交两页的校招简历。
>
> 同理，**不要用 `build.py --check-resume-balance`**——它强制两页契约，对校招简历必然误报（它还依赖 PyMuPDF，多半没装）。

**降级阶梯**：
- 无 WeasyPrint → 只交付 `source.html`（meta.json 的 `render` 记 `html_only`），附一句安装指引（见 README"想直接出 PDF 简历？"节）。占位符检查**不依赖 WeasyPrint，任何情况下都要跑**。
- 无 pymupdf → 不做旧 PDF 抽照片，改为请用户提供照片文件，或不放照片。

## W6 存档

版本命名：基底 `YYYYMMDD-base`；定制版 `YYYYMMDD-<公司slug>-<岗位slug>`（中文 slug = 原文去空格截 8 字；英文 = 小写连字符）；同日同岗第二版加 `-v2`。

`mkdir -p $SKILL_DIR/resumes/versions/<版本id>/`，写**四件套**：

| 文件 | 内容 |
|---|---|
| `source.html` | 终稿 kami HTML |
| `resume.pdf` | 渲染成功才有 |
| `resume.txt` | 终稿纯文本（供未来 pick-base 全文检索） |
| `meta.json` | schema 见下 |

```json
{
  "id": "20260801-tencent-fengkong",
  "base_version": "20260724-base",
  "created_at": "2026-08-01T15:00:00+08:00",
  "target": { "company": "腾讯", "title": "金融科技风控岗", "jd_url": "https://...", "posting_id": "<sha1或null>" },
  "jd_summary": "...",
  "changes": [ "把审计项目重排到首位", "新增扣子工作流项目（已核实：demo阶段）" ],
  "score_before": 68,
  "score_after": 84,
  "honesty_checked": true,
  "render": "pdf | html_only"
}
```

`score_after` = 改后简历对**同一 JD** 按量表重打。然后注册 + 记战绩：

```
python3 $SKILL_DIR/scripts/resume_store.py register --resumes $SKILL_DIR/resumes \
  --id <版本id> --kind tailored --label "<公司>-<岗位>定制版" \
  --txt versions/<版本id>/resume.txt --html versions/<版本id>/source.html \
  [--pdf versions/<版本id>/resume.pdf] \
  --company <公司> --title <岗位> [--posting-id <sha1>] --jd-url <URL> \
  --base <基底id> --score-before <X> --score-after <Y> --tags "<jd_keywords 前几个>"
python3 $SKILL_DIR/scripts/insights.py log-version --insights $SKILL_DIR/state/match_insights.json \
  --version <版本id> --tags "<同上>" --score <Y> --target "<公司>-<岗位>"
```

（定制版**不** `--set-active`——active_base 是总简历，见 resume-profile.md。）

## W7 交付

按 resume-jd-fit **Step 6** 清单自检后交付，必须向用户列出：
- 改动清单（`changes[]`）及每条的依据——尤其 demo 级项目和 AI 相关素材的措辞出处；
- 改前/改后匹配分（score_before → score_after）；
- 存档位置（`resumes/versions/<版本id>/`）与产物形态（PDF 或 HTML）。

最后问一句"投了跟我说一声"。用户说投了 → 按 `references/applications.md` 记一笔，`--resume-version` 填这次产出的版本 id、`--posting-id` 填岗位 id。这一步是"哪一版简历更能过筛"这个统计唯一的数据来源，别省。
