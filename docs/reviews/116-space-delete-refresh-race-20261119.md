# 116 删除空间期间的刷新竞态修复

日期：2026-11-19（Asia/Taipei）。用户先授权只读排查，确认原因后要求修复。修复基于最新 beta1 c25b47d533，在既有 codex/3.1.0-beta1/bugfixes-20261118 独立 worktree 完成。

## 问题及真实证据

116 的 Root 租户（tenant_id=1）由 admin（user_id=3）删除 4431「测试授权 副本」。原复制任务 fc324d55-857e-45c8-b03d-d58d18ed1187 为 failed，1 个文件失败，并非复制成功。

删除任务 a6015bf0-3c4d-4a7b-b678-66eab72e54a9 的持久事实为 business_phase=finalized、state=SUCCEEDED、completed_steps=[fga,minio,es,milvus]、last_error=NULL；knowledge 及 permission mode 已不存在，墓碑为 deleted。以下均为 2026-11-19 本地时间：

| 时间 | 实际动作 |
| --- | --- |
| 11:16:16.092 | POST /api/v1/knowledge/space/4431/deletion/confirm 开始 |
| 11:16:18 | 业务删除提交，墓碑完成 |
| 11:16:19～22 | 浏览器仍请求 4431 的 info、children、my-permissions 及任务列表；空间读取出现 SpaceNotFoundError |
| 11:16:24 | 删除任务四步清理完成 |
| 11:16:25.451 | 确认接口完成，耗时 9.3586 秒；同 trace 已记录删除审计 |

不是靠 HTTP 200 判断成功；核对了任务、墓碑、业务行缺失及原权限删除/清理投影 FINALIZED。116 实际前端包 detail-B99n6BGF.js 同时存在以下两条逻辑：复制清单移除一个任务时使目标空间所有 Query 失效；任务消失且缓存 info.state=1 就弹“副本已创建”。由此在删除已切换、确认响应尚未完成的窗口内误读已删除目标，并误报复制成功。

本次只读取证未重试删除、重建资源、修改数据、重启或部署。

## 修复

1. 整空间删除确认前记录共享 UI 暂停，以 identityKey、tenantId、managementTenantId、view、spaceId 隔离。侧栏和详情使用同一个状态，取消目标在途 Query，停止 info、权限、父路径、目录子树及文件/复制进度子面板；删除对话框保持挂载。其他空间、其他身份/租户/视图及文件级删除不受影响。
2. 确认回执不明时保持原三字段确认，不新建计划；每 2 秒查询原 deletion job，busy 期间不重复请求。只有原任务 succeeded 才成功关闭。成功标记阻止旧空间在退场前再次读取，沿原入口先离开空间再刷新目录。作用域退役和卸载释放未完成的 UI 暂停，迟到 ACK 不恢复旧界面。
3. 复制任务移除只刷新清单，不使该目标空间 Query 失效；仍存在任务的阶段/就绪状态变化保留定向刷新，并排除正在删除的空间。删除基于“任务消失”的自动成功 toast；实际复制进度仍显示原任务结果，遵循 UI 规范“后台状态变化不自动弹成功轻提示”。

Zustand 中的记录仅控制当前页生命周期，不做持久删除事实、权限依据或服务端恢复源。没有增加 API、依赖或表结构；删除鉴权、投影、幂等和后端清理协议均保持。

## 回归与质量检查

- 删除 Hook、两处真实交互入口、复制刷新、侧栏操作、工作台路由及删除对话框 6 文件专项 **70 passed**；覆盖延迟 ACK、丢失 ACK 与自动原任务查询、作用域切换/迟到 ACK、文件级删除不暂停整空间、目标暂停而其他复制任务可刷新。
- 加入完整 f118SpaceDetail 组合为 **105 passed / 1 failed**。唯一失败为已有的 recovers the original copy from a detail page whose target permissions are not initialized，断言旧按钮结构但当前界面已是表格。干净 c25b47d533 基线同文件为 **35 passed / 同一条失败**，本轮未修改该测试或其任务表格实现，不计为新回归。
- pnpm lint（整个 frontend workspace）通过；Platform strict typecheck 通过。
- pnpm check-i18n、architecture guard、git diff --check 通过；5 条新增 QA 用例均为八列结构。
- 整个 frontend typecheck 在 Client 报 14 条类型导出错误，涉及既有 DSH browser config 与 UI 声明导出；干净 c25b47d533 基线相同的 14 条。归一化路径后逐条相同，无新增错误；未修改无关客户端代码或依赖声明。

## 合入前七维自审

使用仓库 sdd-code-review 检查项，仅审本次 bugfix，不宣称整个 F118 验收完成。

| 维度 | 结果 | 证据/限制 |
| --- | --- | --- |
| 边界条件 | PASS | 延迟、丢失及迟到回执、卸载/切作用域、非整空间操作回归 |
| 权限与认证 | PASS | 新状态按身份/租户/管理域/视图隔离；不修改服务端鉴权 |
| 并发安全 | PASS | 保留原确认和 busy 排他，查询原任务，不重复创建删除 |
| 信息泄漏 | PASS | 无凭据、无跨租户数据或新增接口；状态只含资源/操作标识 |
| 测试覆盖 | PASS | 两处真实入口及共享 Hook/Query 的竞态组合；既有失败单独做基线对照 |
| 代码风格 | PASS | Zustand 只存 UI 状态，不发 HTTP；沿原 API 包装和 Query 缓存 |
| 文档同步 | PASS | design §6.12、修订记录、tasks 及八列回归用例同步 |

结论 PASS_WITH_WARNINGS：遗留测试与 Client 类型检查问题已确认同基线，保留说明。116 需正常构建部署前端后，再做真实浏览器验收；本轮没有向 116 写数据或部署构建。
