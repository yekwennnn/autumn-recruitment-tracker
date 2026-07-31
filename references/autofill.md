# 网申草稿填写

## 前置

必须有官方投递 URL、已选简历版本、已确认 application profile。创建 `form_sessions` 后才打开浏览器。
联网前加载 `web-access` skill，依赖检查通过后原样展示它规定的浏览器自动化风险提示。

## 执行入口

通过统一 CLI 创建会话；浏览器检查和填充由 `autofill.py` 执行：

```bash
.venv/bin/python scripts/jobctl.py form start \
  --posting POSTING_ID --resume-version RESUME_VERSION_ID \
  --form-url https://example.com/apply
.venv/bin/python scripts/autofill.py inspect --url https://example.com/apply
```

确认允许代填的字段后，再运行：

```bash
.venv/bin/python scripts/autofill.py fill --url https://example.com/apply \
  --posting-id POSTING_ID --resume-version-id RESUME_VERSION_ID \
  --profile-json /path/to/redacted-or-confirmed-profile.json \
  --resume-file /path/to/resume.pdf --photo-file /path/to/photo.png
```

`fill` 会在开始时创建自己的 `form_session`；如果已经手动创建了会话，仍以本次填表输出的会话为准。
`inspect` 的已填值会脱敏，避免把电话和邮箱写入日志。
脚本通过 Web Access 的本地 CDP Proxy 操作浏览器；没有可用浏览器时只输出人工待填清单，
不得自行安装扩展或伪造“牛客网申助手”存在。

## 可以自动填写

姓名、电话、邮箱、城市、学校、专业、学历、毕业时间、已确认的教育/工作/项目经历、技能、已确认到岗日期、
指定简历上传和用户确认的证件照上传。

## 需要用户确认

期望薪资、异地/出差/加班、转行业、推荐人、主观开放题、自我评价、可能过期的到岗日期。

## 永远不代填/不代勾选

密码、Cookie、短信验证码、图形验证码、身份证号、银行卡信息、健康/残疾/犯罪/征信答案、背景调查授权、
电子签名、法律声明、真实性承诺和最终提交按钮。

## 页面步骤

1. 使用新建后台 tab；不操作用户已有 tab。
2. 先读 DOM 和可见标签，再填写，不盲猜选择器。
3. 每完成一页重新读取 DOM。
4. 未知必填字段写入 `blocked_fields_json` 并暂停。
5. 遇验证码、短信、人脸或登录墙时改为 `blocked`，请用户接管。
6. 上传后检查页面显示的文件名。
7. 完成后写脱敏 manifest，状态改为 `draft_filled` 或 `ready_for_review`。
8. 停在最终提交前，将页面和待确认字段交给用户。

“牛客网申助手”只在直接 DOM 填写失败、用户确认扩展已安装启用并同意后作为浏览器 UI 兜底；不存在时不要安装或假装存在。
