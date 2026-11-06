# F112 真实 E2E 与页面验收清单

状态：未执行；本地隔离链路与组件预览结果见 verification.md。

## 前置条件

- [ ] 专用测试部署已安装 F112（API、Celery 同版本），migration 完成，deploy-limits 声明 version=1、max_codepoints=2000。
- [ ] 专用测试租户和 e2e-f112- 前缀应用已存在；应用包 manifest 与目标 name/slug 相同。无其他同应用在途审批。
- [ ] 普通 owner、普通非 owner、另一租户普通账号、被实际指派的审批人；使用专用简单审批流，首个 pending task 指派给本次审批人。
- [ ] 会话和服务账号 API key 仅注入进程环境，不输出、落盘或提交。禁止把超管短路当普通用户权限证据。
- [ ] 检查专用应用现状；上次 pending 仅按确切测试 instance_id 撤回，旧正式版本是不可变历史，保留并单独记录，不批量删除。

## 一次定向 API 验收

- [ ] 从平台下载新 wheel，核对 manifest SHA，独立安装并运行 version/help/dry-run。
- [ ] 使用新 CLI 提交带 CRLF、多行缩进、中文及 `<script>` 字面值的说明。
- [ ] 轮询到审批，owner 审批详情、审批人 task 详情和版本 GET 均与规范化原文相等。
- [ ] 普通非 owner 与跨租户账号读取版本分别拒绝 16106、16101，审批详情拒绝 18101；拒绝响应无正文泄露。
- [ ] 执行一次驳回，重新 GET 版本和审批，说明保持不变；不额外执行部署故障或资源档位全量测试。
- [ ] 保存源码 SHA、平台镜像/环境标识、CLI SHA、准确 deployment/version/approval IDs 和输入摘要；不记录凭据。
- [ ] teardown 仅撤回本用例未终结申请；不删除既有应用和不可变版本历史。若轮询超时尚无 instance_id，先查确切 deployment_id 再处理，禁止范围清理。

自动化入口：从 backend 目录执行 `python -m pytest test/e2e/test_e2e_vibe_release_notes.py -q`，通过进程环境提供文件顶部列明的 F112_E2E 参数。默认跳过，跳过不记通过。自动用例通过 API 提交；上面的 CLI 下载、安装和提交须补一次在线烟测。

## 页面人工确认（1440px 与 500px）

- [ ] Client 我的申请及我的审批均显示冻结全文、换行和缩进，脚本只显示字面值。
- [ ] Platform 发布页版本历史及版本 tab 同一 version_id 文案一致；翻页、刷新、切换应用不串内容。
- [ ] 历史无说明显示“未填写发布说明”；zh/en/ja 新标题及空态正确。
- [ ] 长行可换行，正文完整可读，审批操作不被挤出。1440/500px 组件预览已经检查，在线页面仍需复核。
