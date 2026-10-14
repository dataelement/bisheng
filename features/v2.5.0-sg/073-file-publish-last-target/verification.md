# 发布路径记忆验证记录

- Status: `LOCAL_VERIFIED`
- Date: `2026-10-14`
- Scope: 当前账号、三个发布分组、user_link 持久化及恢复。无租户分组、无 Schema 变更。
- Code state: 本功能本地工作区最终实现；未提交、未推送、未部署。

## 实际执行证据

| Evidence | 命令或步骤 | 结果 | 范围 |
|---|---|---|---|
| E-001 | 修改前后端 pin/发布选择/提交定向基线 | PASS，34 passed / 77 deselected，退出码 0 | 既有行为 |
| E-002 | 修改前发布弹窗、目录树、分享及 API 四文件 Jest 基线 | PASS，33 passed，退出码 0 | 既有前端行为 |
| E-003 | 新增偏好测试在实现前执行 | 未实现仓储导致 ModuleNotFoundError，收集退出码 2；不是行为回归红灯 | 新增模块缺失 |
| E-004 | 最终后端定向回归（下方命令） | PASS，51 passed / 77 deselected / 6 warnings，4.36 秒，命令退出码 0 | AC-1、AC-2、AC-4 及置顶兼容 |
| E-005 | 最终前端四文件 Jest（下方命令） | PASS，45 passed，4.874 秒，退出码 0 | AC-1、AC-3、AC-4、AC-5 及分享兼容 |
| E-006 | npm run build | PASS，22.17 秒，退出码 0 | 最终客户端构建 |
| E-007 | 新增后端五文件 Ruff check；修改的审批 endpoint/schema/service py_compile；任务路径 git diff --check | PASS，退出码 0 | 定向静态检查；未声明大型旧 service 全量 lint 通过 |
| E-008 | 内置浏览器加载真实 FilePublishDialog / FilePublishTargetTree，使用隔离本地模拟接口 | PASS：二级目录展开且 aria-pressed=true；修改到另一库根目录并提交，新标签页恢复该根目录；失效目标回有效根目录；最终选择二级目录提交，新文件 101 自动恢复 | 浏览器组件场景，非线上或真实数据库端到端 |
| E-009 | 门户整页 publish/发布相关用例与 HEAD 发布弹窗/目录树对照 | 当前与 HEAD 都是 1 passed、4 failed、146 skipped，失败名称和缺失文件行相同 | 既有整页测试缺口，不是新增失败 |

## 最终命令

后端目录 src/backend，使用已有 .venv Python 3.10.19，无依赖安装：

```bash
.venv/bin/python -m pytest   test/knowledge/test_publish_target_preference.py   test/approval/test_file_publish_last_target.py   test/knowledge/test_knowledge_space_pin_repository.py   test/knowledge/test_knowledge_space_pin_integration.py   test/approval/test_shougang_approval_service.py   -k 'pin or file_publish_target or file_publish_submit or publish_target_preference or file_publish_last_target'   -q --disable-warnings
```

客户端目录 src/frontend/client：

```bash
npm run test:ci -- --runInBand --coverage=false --runTestsByPath   src/pages/knowledge/SpaceDetail/FilePublishDialog.test.tsx   src/pages/knowledge/SpaceDetail/FilePublishTargetTree.test.tsx   src/pages/knowledge/SpaceDetail/FileShareDialog.test.tsx   src/api/approval.test.ts
npm run build
```

日志：/tmp/publish-last-target-backend-final.log、/tmp/publish-last-target-frontend-final.log、/tmp/publish-last-target-build.log。

## 规格覆盖

| Acceptance | Status | Evidence |
|---|---|---|
| AC-1 | PASS | E-004 真实 SQLite 不同会话、账号及三个分组；同账号切换租户上下文仍读取同一记录；E-005 独立弹窗挂载读取服务端 |
| AC-2 | PASS | E-004 pending/pass 保存、配置异常不保存、保存失败保持受理结果；E-005 失败提示及旧提交响应不关闭新弹窗 |
| AC-3 | PASS | E-005 根目录和嵌套恢复、提交 ID；E-008 浏览器实际目录展开和选中 |
| AC-4 | PASS | E-004 无权目标不返回 ID/路径、已删/移出目录降级、损坏 JSON 忽略、读写故障隔离；E-005 无效目标和 API 故障降级；偏好及恢复单次 API 超时 5 秒 |
| AC-5 | PASS | E-005 切文件/账号/重新打开丢弃旧恢复，旧搜索与提交不污染新弹窗；共享分享回归通过 |

## 既有整页失败

PortalKnowledgeWorkbench.test.tsx 的以下四项在当前和 HEAD 发布组件上均找不到预期 file-tree-row：

- shows publish action for a successful team space file and submits approval
- shows publish action for a successful business domain space file
- hides publish action without knowledge space publish permission
- disables publish action for non-success file when space publish permission exists

对照只将发布弹窗和目录树替换为 HEAD 版本，保留同一工作区、Jest 环境和用例。临时对照文件已清理。日志保留为 /tmp/publish-last-target-portal-baseline.log。未顺手修复整页文件列表测试。

## 限制、回退及线上边界

- 仓储测试使用 SQLite 内存数据库，验证事务、唯一约束、替换和重复清理；FOR UPDATE 语句已检查，但真实 MySQL/DM8 行锁并发为 MANUAL_REQUIRED。
- 浏览器使用真实组件和本地模拟接口，不代表完整线上发布审批、数据库或跨真实设备联调。
- 浏览器截图：[二级发布目录自动恢复](/tmp/publish-last-target-restored.png)。最终增加的恢复请求超时参数由 API 契约测试与构建验证，未重新执行浏览器超时场景。
- 客户端构建已有字体路径、Browserslist、体积提示，不影响本次构建成功；未扩展修改依赖或字体。
- 本地模拟接口、开发服务器、临时页面及 HEAD 对照文件均已停止或清理；保留截图和日志。
- 无建表、字段变更或迁移；未修改线上数据。回退本功能应用代码即可停用记忆，现有 user_link 专用记录可保留，不影响其他类型。
