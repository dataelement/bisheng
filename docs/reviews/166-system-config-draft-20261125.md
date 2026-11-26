# 166 系统配置编辑草稿在切回窗口后还原

日期：2026-11-25。源码基线：`feat/3.1.0-beta2` 的 `c647c049e7`。修复提交：`edc0c5dc63`。

## 原因

Config 是受控 Ace 编辑器，value 来自 React 的 config 状态。但原 onChange 只更新 codeRef，没有同步 config。ReactAce.componentDidUpdate 会比较编辑器实际内容与 props.value，二者不同时写回 props.value。因此父页面重渲染会将未保存草稿替换为原值。切回窗口会触发身份刷新等页面更新，复制到剪贴板的具体内容不是必要条件。

166 修复前只在自己的浏览器会话内插入一行未保存测试注释，然后派发 blur/focus：注释消失，编辑器与初始内容完全相同；系统配置 GET 请求始终只有 1 次。由此排除这次复现是重新请求配置覆盖草稿。

## 修复

删除 codeRef，编辑和保存都使用 config 状态；onChange 同步 setConfig。保存成功后仍刷新应用配置，但不再重新设置编辑草稿。YAML 校验、加载完成前禁止保存、原错误处理保留；验证 ref 增加类型，移除原 TS strict ignore，并由 lint:prune 删除该文件已解决的未使用变量豁免。

## 验证及边界

- 用真实 ReactAce 和真实编辑器内容变化编写测试，仅隔离 YAML Worker。修复前，重渲染保留草稿、保存失败保留草稿两项失败；修复后通过。
- 三组测试共 10 passed：Config、SystemPage 导航、当前身份焦点刷新。覆盖保存提交值、等待保存响应时继续编辑、保存失败、YAML 校验错误及父组件重渲染。
- workspace lint 通过；原 BatchTagDraftDialog unused-disable warning 保留。platform/client strict typecheck 及共享包类型检查通过；临时工作区 knowledge 包的 tsc wrapper 路径不适配，直接运行同版本编译器 --noEmit 通过。
- platform 生产构建、arch-guard、git diff --check 通过。未修改依赖或锁文件。
- 166 修复后，同样的未保存注释在 blur/focus 和真实切换浏览器标签后均保留；配置 GET 数量仍为 1。测试后移除注释，未点击保存，未修改真实系统配置。
- 本轮未修改 API、权限、身份刷新行为或系统配置持久化格式；不包含页面刷新或关闭后的草稿恢复功能。

## 部署与回退

- 166 前端本地镜像：`bisheng-frontend:3.1.0-beta2-system-config-draft-20261125`。
- 镜像 ID：`2e990b5eaf9a906406ddb00828f3a638ad905ba98a384be39fb5c6d8c479aab7`。
- 基于原引用提示修复镜像，只复制 platform 构建产物，client、Nginx 和后端保持原部署。部署目录 Config.tsx 已同步。
- 私有备份目录：`/opt/bisheng/ops-backups/166-system-config-draft-20261125/`，含 env.before、原镜像 ID、原/新源文件、构建包和构建上下文。不保存系统配置正文或截图中的密钥到仓库。
- 回退时仅将部署 .env 的 BISHENG_FRONTEND_IMAGE 恢复为 `bisheng-frontend:3.1.0-beta2-reference-hints-20261125`，执行 `docker compose up -d --no-deps frontend`。勿整份覆盖其他人的 env 修改。
- 正式注册表镜像和 v3.1.0-beta2 tag 本轮未更新，代码分支交付与镜像发布分别核验。

## sdd-code-review 自审

边界条件、权限认证、并发安全、信息泄漏、测试覆盖、代码风格、文档同步七项均 PASS。保存响应不覆盖较新的编辑；失败保留草稿；没有引入新持久化或跨页面缓存。以上为本轮自审，非独立 agent 审查。
