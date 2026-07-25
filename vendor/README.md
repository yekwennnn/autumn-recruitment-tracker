# vendor/ 内嵌第三方与配套技能说明

本目录存放 autumn-recruitment-tracker「简历工坊」流程依赖的两份内嵌技能。原则：**vendor 内文件除本文注明的路径改写外不做任何修改**；升级方式 = 从上游重新复制覆盖，不在 vendor 内做定制。

## kami/

- 出处：[tw93/Kami](https://github.com/tw93/Kami)（一套"暖纸墨蓝"风格的文档排版技能），MIT License，版权声明原件见 `kami/LICENSE`。
- **当前版本：V1.10.0**（见 `kami/VERSION`）。

### 收录范围

以上游**官方打包目录** `plugins/kami/skills/kami/` 为基底整目录复制，然后只裁掉简历流程确定用不到的重资产。这样做的理由：官方包自带 `VERSION`，脚本的 import 闭环和数据文件依赖由上游保证完整，升级时不需要再手工推演依赖链。

**照单全收**（不做任何删改）：

| 路径 | 说明 |
|---|---|
| `SKILL.md`、`CHEATSHEET.md`、`VERSION`、`LICENSE` | 技能本体与版本标识 |
| `scripts/` 全部 | `build.py` 的 import 闭包是 checks / content / highlight / lint / optional_deps / render / shared / site_facts / tokens / verify / visual，牵一发动全身，整目录收录避免断链 |
| `references/` 全部 | 含 `checks_thresholds.json`（checks.py 读）、`tokens.json`、`mermaid-theme.json`（tokens.py 读，缺了会报 drift 错）、`schemas/`（content.py 按文档类型读）以及各篇写作/设计指引 |
| `assets/images/`、`assets/fonts/JetBrainsMono.woff2` | `resume-en.html` 通过 `@font-face` 直接引用该字体，必须入库 |

**已裁掉**：

| 路径 | 为什么不要 |
|---|---|
| `assets/diagrams/`（16 个图表模板，212K） | 简历流程不出图表 |
| `assets/templates/` 里除 `resume.html`/`resume-en.html` 外的全部 | changelog / equity-report / landing-page / letter / long-doc / one-pager / portfolio / slides / marp / resume-ko，本仓库只做中英文简历 |

**后果（必须知道）**：`kami/SKILL.md` 是上游原文，里面会提到图表路由、marp 幻灯片、韩文模板等本副本**没有内嵌**的东西。走到那些分支会找不到文件。`references/tailoring.md` 已经写明简历流程要声明跳过哪些步骤——改那份文档时别把这条删了。

### 字体

中文主字体仓耳今楷（TsangerJinKai02）是**商业授权字体，上游明令禁止随包分发**，因此不进仓库。构建中文 PDF 前运行：

```bash
bash vendor/kami/scripts/ensure-fonts.sh
```

从官方站点或 CDN 下载到 `kami/assets/fonts/`（该目录的 `.gitkeep` 是脚本运行的前提，请勿删除）。仓库根 `.gitignore` 拦截 `*.ttf`（仓耳今楷）与 `*.otf`（思源宋体韩文，中文流程用不到），确保它们不会被误提交；`JetBrainsMono.woff2` 是 OFL 授权、上游随包分发的，**不在拦截之列，必须入库**。

下载失败也不影响出稿——resume 模板内建 CDN 与系统字体兜底链（Source Han Serif SC → Noto Serif CJK SC → Songti SC → STSong → Georgia）。`build.py --verify` 在缺字体时会打 `[FONT MISS]` 警告但仍然判定 ok，这是预期行为。

### 升级步骤

```bash
# 1. 拉上游最新 tag
git clone --depth 1 --branch <新版本tag> https://github.com/tw93/Kami.git /tmp/kami-up

# 2. 用官方打包目录整体覆盖
rm -rf vendor/kami && cp -R /tmp/kami-up/plugins/kami/skills/kami vendor/kami

# 3. 裁掉不需要的资产
rm -rf vendor/kami/assets/diagrams
cd vendor/kami/assets/templates && ls | grep -v '^resume\(-en\)\?\.html$' | xargs rm -rf && cd -

# 4. 必须实际构建验证，不要只看文件在不在
python3 vendor/kami/scripts/build.py resume
python3 vendor/kami/scripts/build.py resume-en
python3 vendor/kami/scripts/build.py --verify resume

# 5. 清掉构建产物（已 gitignore，保险起见）
rm -rf vendor/kami/assets/examples

# 6. 更新本文的「当前版本」和收录/裁剪清单
```

第 4 步不能省。V1.5.0 上游把 `scripts/` 从 4 个模块拆成了 20 个，只复制 `build.py` 会直接 ImportError——**文件存在不等于能跑**。

### 依赖

`build.py` 的第三方依赖全部是软依赖，缺了会降级不会崩：

| 包 | 缺了会怎样 |
|---|---|
| `weasyprint`、`pypdf` | 出不了 PDF，抛 `MissingDepError` 并给出安装提示；本仓库流程降级为交付 HTML |
| `numpy` | `checks.py` 的留白密度检测退回纯 Python 循环，只是慢一点 |
| `pygments` | 代码块单色渲染，打一行警告 |
| `pymupdf`（fitz） | 部分视觉检查不可用 |

## resume-jd-fit/

- 本仓库作者原创技能的内嵌副本，随本仓库 MIT 协议分发。
- 相对原版仅两处改动：文件头部加了一段"内嵌副本"注释；一处 `kami` skill 引用改写为指向 `vendor/kami/` 路径。其余内容（诚实性核查、保密脱敏、一页排版修法）与原版一致。
