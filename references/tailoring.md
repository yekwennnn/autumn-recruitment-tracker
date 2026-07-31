# JD 定制简历

只有用户明确选择岗位并要求修改时进入；定时任务禁止进入。

## 顺序

```text
读取 JD → 选择基底 → 读取 confirmed_facts → 分析差距 → 核实事实 → 用户确认改动清单
→ STAR 改写 → Kami 排版 → 照片处理 → 占位符检查 → PDF 视觉 QA → 注册版本 → 重评分
```

差距只能分三类：

- `presentation_gap`：简历已有事实，只改排序和表达。
- `information_gap`：可能有经历，必须询问用户。
- `capability_gap`：用户确认没有，不能写进简历。

每问出一个新事实就写入 `confirmed_facts`。每条经历按背景/任务、本人动作、真实结果组织；没有数字就写规模、
状态或交付对象，不编造指标。demo、个人使用和正式上线必须分开描述。

## Kami

读取 `vendor/kami/SKILL.md` 和 resume-writing 规范。校招模板为 `assets/templates/resume-campus-cn.html`，社招为
`assets/templates/resume-social-cn.html`。模板 CSS 不直接改，body 由 `assets/*-body.html` 和 `scripts/make_templates.py`
生成。

中文简历默认要求用户照片。照片优先用用户文件，否则尝试从旧 PDF 第一页提取最大嵌入图片；不能生成真人照片。
照片转 data URI，不写文件路径。缺照片时可完成文字改写，但停止 PDF 交付并请求照片。

## 交付前检查

```bash
python3 vendor/kami/scripts/build.py --check-placeholders <绝对HTML路径>
python3 vendor/kami/scripts/build.py --check-markdown <绝对PDF路径>
```

随后检查页数、字体和首屏 PNG。校招一页；社招最多两页。最终注册 `source.html`、`resume.txt`、`resume.pdf`、`meta.json`，
记录基底、岗位、改动清单、诚实性核查、改前/改后分数和照片来源。
