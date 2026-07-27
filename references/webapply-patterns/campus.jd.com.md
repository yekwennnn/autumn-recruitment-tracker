---
domain: campus.jd.com
system: 自研（Ant Design + React）
aliases: [京东校招, 京东校园招聘, JD校招]
updated: 2026-07-27
verified_on: [2026-07-27 实测：在线简历表单读取与填写，未点保存]
---

京东校招用的是自研系统，前端 **Ant Design + React**。不是北森／Moka／大易任何一家，
`beisen.md` 那套经验（bsrc- 前缀、必须 clickAt、innerText 判空）在这里**全都不适用**，
别套用。

## 系统识别特征

- 域名 `campus.jd.com`（社招是 `zhaopin.jd.com`）。
- 组件类名前缀 **`ant-`**（`ant-select`、`ant-cascader-picker`、`ant-upload`、`ant-modal-wrap`、`ant-btn`）。
- 业务组件用 CSS Modules 哈希类名（`addBtn___3r3aQ`、`deleteBtn___Eh49h`、`filedValue___orYso`
  ——注意 `filed` 是官方拼写错误，不是笔误）。哈希会随前端发版变化，**别把哈希当长期选择器**，
  优先用 `ant-` 前缀 + textContent 定位。
- **hash 路由**：`https://campus.jd.com/home#/resume?type=present`。用 `/new` 开 tab 时
  `#` 必须写成 `%23`，否则 query 被截断。

## 页面形态：在线简历中心（不是逐岗申请表）

**这一点决定了整个流程怎么走**：`#/resume` 是一份"京东简历"，底部只有「返 回」和「保 存」，
**没有提交按钮**。投递发生在职位页——选好岗位后引用这份简历。

所以：
- 点「保 存」**不等于投递**，不要在保存后调 `apply.py mark`；
- 但「保 存」会覆盖线上已有的简历，仍然需要用户点头（见 webapply.md 第 5 节的两形态规则）。

## 表单分步结构

单页长表单，顶部锚点导航跳转，共 12 节：

招聘信息来源 / 简历附件 / 基本信息 / 教育经历 / 实习经历 / 校园经历 / 项目经历 /
荣誉奖励 / 论文期刊 / 发明成果专利 / 语言证书技能 / 其他信息

可重复的节（教育、实习、校园、项目、荣誉、论文、专利、语言证书）每节末尾一个
`.addBtn___3r3aQ`「+ 添加」，已有条目带 `.deleteBtn___Eh49h`「删除」。
页面上 addBtn 的 DOM 顺序 == 上面可重复节的顺序，最后一个（index 7）是语言证书节。

## 字段与控件对照表

| 字段类型 | 控件 | 定位 | 填写方法 |
|---|---|---|---|
| 文本／多行 | React 受控 `input`/`textarea` | 按 DOM 序遍历 `input,textarea` | 原生 setter + dispatch `input`/`change`（见 webapply.md 第 4 节）——**实测有效** |
| 下拉 | `.ant-select` | `[...document.querySelectorAll(".ant-select")]` 按序号取 | `el.querySelector(".ant-select-selection").click()` 展开，**普通 `click()` 即可，不需要 clickAt** |
| 下拉选项 | 浮层 | `.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-dropdown-menu-item` | 按 `textContent.trim()` 精确匹配后 `.click()` |
| 级联（籍贯／专业类别） | `.ant-cascader-picker` | 同上按序号 | `.click()` 展开；读 `.ant-cascader-menus:not(.ant-cascader-menus-hidden) .ant-cascader-menu` 得到各级菜单数组，逐级点 `.ant-cascader-menu-item` |
| 单选 | `input[type=radio]` | 读 `.checked` 判当前值 | 常规 |
| 附件 | 隐藏 `input[type=file]` | 第 1 个=简历(pdf/doc/docx)、第 2 个=头像(image/*)、第 3-6 个=成绩单/证书/专利/作品集 | `/setFiles` 绝对路径——**但必看下方「简历绑定」陷阱** |

**实测过的枚举值**（省得再点开一遍）：

- 学历层次：专科 / 本科 / 硕士 / 博士 / MBA
- 专业成绩排名：前5% / 前10% / 前20% / 前30% / 前40% / 前50% / 其他
- 技能类型：外语语种 / 证书 / 开发语言 / 其他技能
- 外语语种：英语 / 日语 / 韩语 / 德语 / 法语 / 阿拉伯语 / 马来西亚语 / 西班牙语 / 其他
- 专业类别：二级级联，一级为学科门类（法学/经济学/哲学/理学/历史学/文学/教育学/农学/工学/管理学/医学/其他）；
  管理学下有 **财会管理相关类**、工商管理相关类、市场营销相关类、人力资源管理相关类等
- 籍贯：省市二级级联，一级是 34 个省级行政区全名（"浙江省"而非"浙江"）

## 已知陷阱

**① 「简历绑定」对话框会吃掉你的整份简历（2026-07-27，严重）**

`/setFiles` 传简历附件后，页面弹出 `.ant-modal-wrap`：

> 简历绑定 —— 是否根据您上传的附件信息，自动填写至京东简历详情中？**信息自动填写后，原来的信息将丢失。**
> 　[否，仅上传附件]　[是，上传并解析]

- **「是，上传并解析」= 用 PDF 解析结果覆盖表单全部现有内容**，用户几年积累的校园经历、荣誉、
  自定义描述全没。**任何情况下不要点它**，除非用户在看到这段警告原文后明确要求。
- 「否，仅上传附件」才是"只换附件"，实测选它之后附件名正确更新、其余字段一字未动。
- 对话框未处理时上传处于挂起态：`input.files.length` 归 0（组件已读走文件）但附件名不变，
  容易误判成"上传失败"而重试。**setFiles 之后先查弹窗，再判断成败。**
- 点击前按文本精确匹配并二次校验：匹配数 ≠ 1 就中止；文本含"解析"就拒绝点击。

**② 表单里可能躺着几年前的旧数据（2026-07-27）**

京东简历是长期账号资产，实测遇到的是一份约两年前填的版本：只有本科学历、缺最新实习、
邮箱是旧的，但页面顶部照样显示「简历完成度：100%」——**完成度不代表内容是新的**。
所以这个站点必须走 webapply.md S5 的 diff 模式（现值 vs 拟改为），不能当空表填。

**③ 职位名称字段有多重 HTML 转义 bug（2026-07-27）**

实测读到形如 `x&amp;amp;amp;amp;amp;y实习生` 的值，原值只是含一个 `&` 的普通职位名——
含 `&` 的字段疑似每保存一次转义一层。遇到 `&amp;` 链要还原成 `&` 再写回。填写时直接写 `&` 即可。

**④ 教育经历的「是否最高学历」是手工维护的（2026-07-27）**

只有一条本科时它勾着"是"。新增硕士块之后**必须把本科那块改成"否"**，否则学历信息自相矛盾。

**⑤ 截图接口的中文路径（2026-07-27，属工具坑不是站点坑）**

`state/tmp/webapply/` 的绝对路径里含中文（用户目录是 `求职工作台`），
`curl "…/screenshot?target=X&file=/中文/路径.png"` 会**静默失败**：接口返回正常但文件不落盘。
必须用 `curl -G --data-urlencode "file=$ABS"` 让 curl 做 URL 编码。

**⑥ 探测下拉后要收尾**

点开 `.ant-select` / `.ant-cascader-picker` 读枚举值之后，浮层不会自动关，会叠在页面上
干扰后续截图和点击。用 `document.body.click()` + `dispatchEvent(new MouseEvent("mousedown"))`
清场，并用
`document.querySelectorAll(".ant-select-dropdown:not(.ant-select-dropdown-hidden), .ant-cascader-menus:not(.ant-cascader-menus-hidden)").length === 0`
确认已清干净。

## 提交与保存按钮辨识

- 「保 存」：`.ant-btn`，文案含全角空格（`保 存`），页面最底部，红色主按钮。**非投递**，但覆盖线上简历。
- 「返 回」：`.ant-btn`，同区域左侧。
- 底部另有必勾的**声明条款** checkbox（京东招聘隐私政策）——实测已勾选状态；
  若未勾选，按 webapply.md 的规矩这属于"接受条款"，**要用户自己勾**，不代劳。

## 待验证

- 点「保 存」后的返回与校验行为（本次未点）。
- 职位页的"申请"入口长什么样、如何引用这份简历、投递成功页特征。
- 头像上传（第 2 个 file input）是否也有裁剪弹层。

## 变更记录

- 2026-07-27 初建。实测覆盖：表单读取、受控输入写入、antd 下拉与级联、setFiles 换附件、
  「简历绑定」弹窗规避、新增语言证书行。未点保存。

---

> **写入规则**：本文件只记录页面结构、选择器和操作策略。
> 绝不写入任何个人数据、开放题答案文本或账号信息。
