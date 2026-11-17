# Code Review Report

**Feature**: 知识空间分段与覆盖上传修复
**Review scope**: 最新 beta1 基线上的本次工作区差异，关联 F015/F118 既有规格；补充完成 116 只读复制/移动诊断；部署和现场数据恢复不在本次执行范围。
**Base branch**: `origin/feat/3.1.0-beta1`（本次基线 `97487e9f25`）

## Summary

| Dimension | High | Medium | Low | Status |
|-----------|------|--------|-----|--------|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 1 | 0 | PASS_WITH_WARNINGS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync | 0 | 0 | 0 | PASS |

## 已检查的重点

- 更新/删除先按实际空间 edit、文件/版本归属验证，再由统一权限入口要求文件 visible，之后才有索引 IO。文件重处理及目标读取也使用 visible；空间级重建范围未被意外缩小。
- 专用类型不提交普通覆盖参数；预览与参数配置复用原有组件。预览明确只读，避免缓存内的人工改动在任务中静默丢失。
- 页面通过 URL 和完整身份/租户/空间键隔离；返回保留原目录，切换空间/目录清理旧处理目标；非法、重复目标参数拒绝。
- 冲突项按物理 ID 取最后一份，与既有 tmp 对象覆盖顺序一致；严格重复 ID 拒绝保留在后端。新登记结果与冲突结果分开处理。
- 复制空集合复用标准 schema bootstrap，在 load 前创建集合并清理 seed；两个模型读仍使用持锁事务，避免跨连接自身等待。移动只接受 state=1 的就绪源/目标，拒绝未初始化复制目标；旧任务冻结权限版本变化不被重写。
- 未新增 API、数据库结构、权限投影、存储客户端依赖、跨租户查询、删除绕过或迁移配额变化。

## 验证

- 后端：14 个相关测试文件共 **133 passed**；新增完整上传/重复 ID 拒绝/合并后覆盖回归 **1 passed**，合计 **134 passed**。覆盖 Chunk 可见性、处理 API→Owner→原生解析/写入、复制/移动和恢复、迁移 CLI 及配额口径。SQL 使用隔离测试库，外部存储、模型、FGA 等边界按既有 fixture 隔离。
- 116 根因补充修复：复制/移动的 14 个测试文件 **213 passed**（两组分别 57、156，无文件重叠；与前述初批存在重叠，不相加声称独立总数）。新增空 Milvus 集合的实际 schema helper 执行/失败回归，覆盖未初始化源/目标的移动预检、确认及既有执行控制。
- Platform：8 个相关测试文件共 **129 passed**，覆盖规则类型、预览前禁止确认、原计划确认、独立页面入口、文件详情、目录切换、非法处理目标及原功能兼容。
- Client：上传 helper 与错误处理 **30 passed**，含五次相同冲突合并为一次并保留最后响应、新文件不丢失。
- 工作区 `pnpm lint`、`pnpm typecheck`、`check-i18n` 全部通过。
- 修改的 Python 应用/测试 Ruff 检查通过；旧 `knowledge_service.py` 全文件有 **38** 条既有 Ruff 问题，与基线比较无新增；知识模块 F821 检查通过。
- 修改代码逐文件 arch-guard 无输出；`git diff --check` 通过。

## MEDIUM

- 已只读核对 116 SQL、日志和 ES HEAD，复制/移动根因已明确并形成补充修复；新代码仍未在真实解析服务/存储/索引及 DM8 上执行，浏览器视觉尚未实测，旧失败任务未恢复。现场清单见 [排查记录](knowledge-processing-bugfix-20261117.md) 及 [116 取证](knowledge-copy-move-116-20261117.md)。

## Overall: PASS_WITH_WARNINGS（针对已修复代码范围）

本地代码修复及现场根因排查已完成，未执行部署及历史任务/数据恢复；预检影响项依用户要求先列清单，未变更迁移配额行为。
