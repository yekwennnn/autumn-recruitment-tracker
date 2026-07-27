# 网申自动填表

监控发现岗位、深评给分、改简历、追踪投递——中间还缺一段最耗人的：**把同样的信息在几十家公司的网申系统里重填几十遍**。北森、Moka、大易这些系统长得都差不多，字段也大同小异，但每家都要求你从头填一遍教育经历、实习经历、开放题。

这一节把这段自动化：个人信息存成结构化档案（一次录入，处处复用），填表时读页面 DOM 生成字段映射，你核对无误后逐节写入，**停在提交按钮前面等你点头**。

数据存 `resumes/webapply-profile.json`，唯一写方是执行本流程的 orchestrator（AI 直接读写，和 `config.json` 同样的惯例）。

---

## 0. 安全红线

这六条是硬约束，任何情况下不得绕过，用户明确要求也不行。

1. **绝不代填、绝不存储**：密码、验证码、身份证号／护照号、银行卡号。档案 schema 里**没有**这些字段，将来也不许加。表单里遇到这类必填项 → 截图指出位置，告诉用户"这一格我不碰，你来填"，等用户填完说"好了"再继续。**填完不回读、不记录该字段的值。**
2. **绝不代注册账号、绝不代过验证码／滑块／人机验证**。登录一律由用户本人在自己的 Chrome 里完成。
3. **填写前用户须确认字段映射**；**每一次**点击「提交／确认提交／Submit／申请／投递」这类不可逆按钮之前，都必须重新取得用户的明确同意——不存在"这次会话已经授权过了"。默认流程走到提交前就停下，用户可以选择让你点，也可以自己点。
4. **只在自己用 `/new` 开的后台 tab 里操作**，绝不碰用户已经打开的 tab，做完 `/close` 关掉自己开的。
5. **档案内容与页面截图永不注入子 agent 的 prompt、永不外发**。真实姓名、手机号、邮箱只经 CDP 写进用户本机浏览器的表单里，不出本机。这与 `resume-profile.md` 的隐私红线一致。
6. **无人值守（定时任务）绝不进入本流程**。填表全程需要人在场确认。

---

## 1. 触发与前置检查

**触发语**：「帮我填 XX 的网申」「自动填一下网申」「投一下 XX 官网」——通常带一个网申链接或公司名。

**前置检查按顺序做**：

1. 加载浏览器能力：优先用技能加载工具加载 `web-access`；加载不了就直接读 `~/.claude/skills/web-access/SKILL.md` 按其指引操作。
2. 依赖自检：
   ```bash
   export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"; node ~/.claude/skills/web-access/scripts/check-deps.mjs
   ```
   不通过就按它的提示引导用户（Node 22+；Chrome 需在 `chrome://inspect/#remote-debugging` 勾选 "Allow remote debugging for this browser instance"，可能要重启 Chrome）。
3. **原文向用户展示 web-access 的自动化风险提示**（这是它的 SKILL.md 要求的规定动作，不要改写、不要省略）：
   ```
   温馨提示：部分站点对浏览器自动化操作检测严格，存在账号封禁风险。已内置防护措施但无法完全避免，Agent 继续操作即视为接受。
   ```
4. 启动／复用代理并探活：
   ```bash
   curl -s http://localhost:3456/health
   ```
   没起来就先启动（已在跑会提示端口占用，直接复用即可）：
   ```bash
   export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"; node ~/.claude/skills/web-access/scripts/cdp-proxy.mjs &
   ```

以上任何一步彻底不可用 → 走第 8 节的降级路径，**不要硬撑**。

---

## 2. 网申档案初始化

**什么时候触发**：`resumes/webapply-profile.json` 不存在，或 `completion.status != "ready"`，或用户要求重建。

### 2.1 抽取

读这三个源，按 schema 尽量填满：

- `resumes/versions/<active>/resume.txt` —— **唯一含真实联系方式的来源**（姓名、手机、邮箱、微信都在第一行）
- `resumes/profile.json` —— 已结构化的教育／实习／项目／技能（注意它的 `name_masked` 是脱敏的，别用）
- `resumes/index.json` —— 确认 active 版本，附件要传哪个 PDF 靠它解析

抽取时**只搬运，不发挥**：简历里没写的就留空，不要从专业名称推断出政治面貌，也不要把"旺季""暑期"这类模糊表述猜成具体月份。

### 2.2 核对

把抽出来的内容**分块展示**给用户逐块确认（基本信息 / 教育 / 实习 / 项目 / 获奖 / 技能与自我评价 / 求职意向）。同时把"简历里没写、我留空了"的字段单独列一份清单——这比让用户自己发现漏了什么强。

### 2.3 补问缺口

网申表单必填、但简历上通常没有的字段，**一次问完**（能用选项式提问就用选项式）：

| 字段 | 说明 |
|---|---|
| 性别 / 出生年月 | 几乎每家必填 |
| 籍贯 / 户口所在地 / 现居城市 | 北森系尤其爱问，通常是省市级联下拉 |
| 民族 / 政治面貌 | 国企央企必填，外企一般没有 |
| 英语等级 | 有雅思托福也要单独问四六级分数——国内系统的选项里常常只有 CET |
| GPA 与排名 | 问清楚分制（4.0 / 5.0 / 百分制） |
| 实习起止年月 | 简历上常写"暑期""旺季"这种模糊表述，表单要精确到月 |
| 期望城市 / 到岗时间 | 求职意向节必填 |
| 证件照 | 请用户把图片文件放进 `resumes/photos/`，告诉你路径 |

用户明确拒答或表示不适用的，写进 `declined_fields`，**以后不要再问第二遍**。

### 2.4 落盘

写回 `resumes/webapply-profile.json`，把 `completion.status` 置为 `ready`，`missing` 清空（或只留用户拒答的），更新 `updated_at`。向用户复述一句摘要。

之后每次填表遇到新的缺口字段，问完立刻回写档案——**档案越用越全，第二家公司就比第一家省事**。

---

## 3. 单次填表流程

状态机，按顺序走。每一步都有明确的产出，别跳步。

**S1 开 tab** —— `curl -s "http://localhost:3456/new?url=<网申链接>"`，保留 URL 的完整 query 参数（很多系统靠参数定位岗位）。记下返回的 `targetId`，后续所有请求都带它。

**S2 判断登录态** —— 标准是「我要的东西拿到了吗」，不是「页面上有没有登录按钮」。读不到申请表内容 → 告诉用户"需要你先在 Chrome 里登录这个站点（含验证码），登录好了跟我说一声"，等用户回话后 `/navigate` 刷新继续。**不要试图代登录。**

**S3 读经验** —— 先查本技能的 `references/webapply-patterns/`：精确域名文件（如 `dreame.zhiye.com.md`）优先，没有就按系统识别特征匹配系统级文件（如 `beisen.md`）。再顺手看一眼 web-access 的 `references/site-patterns/{domain}.md`（那边记的是浏览层经验，可能有反爬、innerText 之类的坑）。

**S4 读表单结构** —— 用 `/eval` 遍历 DOM，提取：分步向导有几步、当前这步有哪些字段、每个字段的 label／控件类型／是否必填／可用的选择器。注意穿透 iframe 和 shadowRoot。北森系记得用 `textContent` 而不是 `innerText`（见 `webapply-patterns/beisen.md`）。

**S5 生成字段映射预览表** —— 发给用户：

| 表单字段 | 必填 | 将填入 | 来源 | 备注 |
|---|---|---|---|---|
| 姓名 | ✅ | 〈档案里的真实姓名〉 | 档案 basic.name | |
| 身份证号 | ✅ | —— | —— | **红线字段，需你手填** |
| 最高学历毕业院校 | ✅ | 〈档案里的学校〉 | 档案 education[0].school | |
| 期望城市 | ✅ | —— | 档案缺 | 现场问你，答完写回档案 |

（示例里用占位符是有意的：这份文档要入库，不能带真实信息。实际发给用户的表要填真值。）

档案里没有的字段**当场问**，问到就写回档案（第 2.3 节的规矩）。红线字段一律标「需你手填」，不给建议值。

**S6 等确认** —— 用户确认这张表之后才开始写入。用户要改哪一格，改完重新出表。

**S7 逐节填写** —— 一节填完做三件事：`/eval` 读回已填的值核对、`/screenshot` 存截图、简短汇报这节填了什么。写不进去的字段见第 4 节的处置规则。

截图存 `state/tmp/webapply/<YYYYMMDD-HHMM>/section-N.png`，`file` 参数必须给绝对路径（用 `$PWD` 拼）。

**S8 多步向导** —— 「保存」「下一步」「暂存」这类**非终局按钮**，告知用户一声后可以直接点。每进入新的一步，回到 S4 重新读这一屏的字段。

**S9 提交前停下** —— 整页截图 + 汇总"已填 N 节 M 个字段，留空 X 项（列出来）"，请用户核对。**默认到此为止**。用户明确说要提交 → 再复述一次「我将点击『提交』，这一步不可逆」，取得二次确认后才 `/click`；或者干脆让用户自己在浏览器里点。

**S10 提交之后** —— 成功页截图 → 按第 9 节记投递 → 按第 10 节写回 pattern 经验 → `/close` 关掉自己开的 tab。

---

## 4. 特殊控件策略

网申表单的坑基本都在控件上。按类型对症下药：

| 控件 | 怎么认 | 怎么填 |
|---|---|---|
| **React 受控 input／textarea** | 有 `value`，但直接赋值被组件吞掉 | 用原生 setter 绕过 React 的劫持：<br>`const s=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; s.call(el,v); el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));`<br>textarea 用 `HTMLTextAreaElement.prototype` |
| **原生 select** | `<select>` 标签 | 设 `value` 后 dispatch `change` |
| **自绘下拉 / 级联地区** | 点开是 div 浮层，不是 `<option>` | 先 `/click` 展开，浮层里按 `textContent` 定位选项；没反应就换 `/clickAt`。省市区**逐级选**，每级选完等浮层刷新再选下一级 |
| **日期选择器** | 自绘日历弹层 | 优先找背后的隐藏 `input` 直接用原生 setter 写；找不到才逐月翻页点日期 |
| **单选 / 复选 / 树** | 北森系类名含 `bsrc-` | **必须 `/clickAt`**，合成 `el.click()` 对这类组件无效。点完读 className 确认状态（如含 `bsrc-tree-checkbox-checked`），**别只看截图判断**——选中态的视觉变化常常很不明显 |
| **富文本编辑器** | `contenteditable` | `/eval` 设 `innerText` 后 dispatch `input` |
| **文件上传** | `input[type=file]`，常被 CSS 藏起来 | `/setFiles`，body 传 `{"selector":"input[type=file]","files":["<绝对路径>"]}`，完全绕过文件对话框。找不到 file input 才考虑 `/clickAt` 触发对话框——但那需要用户手选文件，不如直接请用户操作 |

**通用规矩**：

- 每次写入之后必须读回验证，写了不等于写进去了。
- **同一个字段连续两次写不进去就停手**，标记「请用户手填这一格」，继续填其余字段。不要在一个控件上死磕十几轮——那是在烧时间，也容易触发站点的异常检测。
- 填写节奏不必刻意放慢，但也不要用循环高频打 API。

---

## 5. 必须停下来找用户的场景

- 验证码、滑块、拼图、人机验证 —— 红线②
- 身份证／护照／银行卡／密码 —— 红线①
- 任何涉及支付的字段
- 需要短信验证码确认的操作
- 表单要求上传证件照片（身份证正反面、学生证）——这类文件不在档案里，请用户自己传

处理方式统一：截图 + 说清楚在页面的哪个位置 + 等用户。

---

## 6. 开放题答案库

网申的开放题（「为什么选择我们公司」「你最大的失败经历」「职业规划」）是最耗时的部分，也是最值得复用的——同一道题换个公司只需微调。

存在档案的 `custom_answers` 里。遇到开放题：

1. **先在库里做语义匹配**（不是字符串精确匹配——「谈谈你的职业规划」和「请描述你未来三年的发展计划」是同一道题）。
2. 命中 → 把已有答案展示给用户，问：直接用 / 按这家公司微调 / 重写。微调后的版本存进该条的 `company_variants`，通用版保持不动。
3. 没命中 → 基于简历和用户口述草拟，用户确认后写入库（带上 `tags` 和 `created_at`）。

**诚实红线和改简历一致**（见 `tailoring.md`）：答案可以挑角度、可以润色表达，**不能编造没发生过的经历**。用户自己要求写进去的除外，但要提醒一句。

---

## 7. 临时文件

截图和中间产物一律写 `state/tmp/webapply/<运行时间戳>/`（已被 gitignore）。本流程**开始时清理上一次的 `state/tmp/webapply/` 目录**——SKILL.md 第 1 步的清理只删 `state/tmp` 下的 `*.json`，不管这里。

和主管线一样：**不要用 `/tmp`**。

---

## 8. 降级路径（CDP 不可用）

浏览器能力起不来，档案照样有价值——只是从"自动填"退化成"照着抄"：

1. 第 2 节的档案初始化照常做完。
2. 请用户把表单字段清单贴过来，或者截图发过来。
3. 产出一张**字段-答案清单**：

   | 表单字段 | 建议填入 | 备注 |
   |---|---|---|

   开放题附完整答案全文，方便直接复制粘贴。
4. `custom_answers` 照常沉淀——下次不管有没有 CDP 都省事。

---

## 9. 记这次投递

**只在真实提交成功之后才记。** 停在提交前没投的，不要记账，改为提醒用户："等你提交了跟我说一声，我来记。"

岗位在监控库里（用户从日报里挑的）：

```bash
python3 $SKILL_DIR/scripts/apply.py mark \
  --applications $SKILL_DIR/state/applications.json \
  --state $SKILL_DIR/state/seen_postings.json \
  --posting-id <岗位id> --resume-version <这次投出去的版本id> --channel 官网网申
```

库外的 ad-hoc 链接（用户自己找到的网申）：

```bash
python3 $SKILL_DIR/scripts/apply.py mark \
  --applications $SKILL_DIR/state/applications.json \
  --company <公司> --title <岗位> --resume-version <版本id> \
  --channel 官网网申 --note "<网申链接>"
```

`--channel` 固定填 `官网网申`，方便以后按渠道算过筛率。`--resume-version` 别省，理由见 `applications.md`。

---

## 10. 写回 pattern 经验

一次填表走完（**不管最终有没有提交**），把验证过的结构性事实写回 `references/webapply-patterns/`：

- **系统级共性** → 写进系统文件（`beisen.md` 等）。「北森的日期控件背后有隐藏 input」这种，对所有北森系公司都成立。
- **单公司特例** → 新建 `{domain}.md`（如 `dreame.zhiye.com.md`）。「这家的实习经历节最多只能填 3 段」这种。
- **纯浏览层的新发现**（反爬、innerText 判空之类，与填表无关）→ 按 web-access 自己的约定写回它的 `references/site-patterns/`。

模板见 `webapply-patterns/_template.md`。

**写回之前 grep 自检一遍**：pattern 文件里绝不能出现姓名、手机号、邮箱、或任何开放题答案文本。只记结构、选择器、操作策略。

```bash
grep -niE "1[3-9][0-9]{9}|[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}" references/webapply-patterns/*.md
```

再对着档案里的 `basic.name` 搜一遍真实姓名（这里不写死，避免把姓名留在入库文件里）。有命中就把那几行改掉再存。
