# vendor/ 内嵌第三方与配套技能说明

本目录存放 autumn-recruitment-tracker「简历工坊」流程依赖的两份内嵌技能。原则：**vendor 内文件除本文注明的路径改写外不做任何修改**；升级方式 = 从上游整目录重新复制覆盖，不在 vendor 内做定制。

## kami/

- 出处：Tw93 的 kami 项目（一套"暖纸墨蓝"风格的文档排版技能），MIT License，版权声明原件见 `kami/LICENSE`。
- 本仓库只收**简历流程所需子集**（SKILL.md、CHEATSHEET.md、resume 模板、构建脚本、设计/写作/生产/反模式/简历写作参考、tokens.json），文件内容零修改。
- 未收录：`assets/fonts/*.ttf`（见下）、`assets/demos/`、`assets/diagrams/`、`JetBrainsMono.woff2`（resume 模板未引用）、`stabilize.py`/`package-skill.sh`/测试、`brand-profile.md`/`brand.example.md`/`diagrams.md`/`stabilizer_profiles.json`、官网文件（index*.html/styles.css/llms.txt/robots.txt/sitemap.xml/vercel.json）、`CLAUDE.md`/`AGENTS.md`/`.github`/`.claude-plugin`/`.gitignore`/`README.md`。
- **字体说明**：中文主字体仓耳今楷（TsangerJinKai02）为商业授权字体，kami 明文规定不得随包分发，因此不进仓库。构建 PDF 前运行：

  ```bash
  bash vendor/kami/scripts/ensure-fonts.sh
  ```

  从 CDN 下载到 `kami/assets/fonts/`（该目录的 `.gitkeep` 是脚本运行的前提，请勿删除；下载下来的 TTF 已被仓库根 `.gitignore` 拦截，不会被误提交）。下载失败也不影响出稿——resume 模板内建 CDN 与系统字体兜底链（Source Han Serif SC → Noto Serif CJK SC → Songti SC → STSong → Georgia）。

## resume-jd-fit/

- 本仓库作者原创技能的内嵌副本，随本仓库 MIT 协议分发。
- 相对原版仅两处改动：文件头部加了一段"内嵌副本"注释；一处 `kami` skill 引用改写为指向 `vendor/kami/` 路径。其余内容（诚实性核查、保密脱敏、一页排版修法）与原版一致。
