# F073 E+ 机器人接入 E2E 验收记录

**记录日期**：2026-09-28  
**当前结论**：PARTIAL。代码级自动化和客户 E+ 协议探针已通过；毕昇完整链路、MySQL/DM8、双实例 Redis、跨进程 MinIO 仍需在客户测试环境执行。

## 1. 已执行的自动化

| 范围 | 命令 | 结果 |
|---|---|---|
| E+ 后端全套 | `pytest -q src/backend/test/eplus` | 119 passed；包含协议、媒体、身份、队列、范围、回复、长连接、租约、编排和 Worker 生命周期 |
| 安全与既有助手/F041 回归 | `pytest` 运行安全守卫及 assistant、space retrieval、日常附件相关用例 | 43 passed，另 6 个 subtests passed |
| E+ 管理页 | `pnpm --dir src/frontend --filter bisheng test -- eplusRobotSettings.test.tsx` | 3 passed |
| 前端 lint | `pnpm --dir src/frontend lint` | 通过 |
| 前端 i18n | `pnpm --dir src/frontend check-i18n` | 通过 |
| 前端 typecheck | `pnpm --dir src/frontend typecheck` | Platform 通过；Client 被既有的 `AgentToolSelector.tsx:139`、`ChatFormTools.tsx:118` 两处无关错误阻断 |
| 架构守卫 | `bash scripts/arch-guard.sh` | 通过 |
| Alembic 单头 | `alembic heads` | `f061_merge_cofco_909_f066_heads (head)` |
| Shell | `bash -n src/backend/entrypoint.sh docker/bisheng/entrypoint.sh` | 通过 |
| Compose | `docker compose ... config --quiet` | 未执行：本机未安装 Docker CLI；YAML 与服务约束由 Worker 生命周期测试解析验证 |
| 环境只读 E2E | `pytest -q src/backend/test/e2e/test_e2e_eplus_robot_assistant.py` | 本地因未提供 `E2E_EPLUS_ASSISTANT_ID` 跳过；客户环境按下文命令执行 |

客户环境只读 E2E 命令：

```bash
E2E_API_BASE=http://127.0.0.1:7860/api/v1 \
E2E_ADMIN_TOKEN='<临时测试令牌>' \
E2E_EPLUS_ASSISTANT_ID='<测试助手ID>' \
pytest -q src/backend/test/e2e/test_e2e_eplus_robot_assistant.py -v
```

## 2. 已通过的客户 E+ 协议探针

客户测试环境于 2026-09-28 验证通过：DNS、TCP/TLS、订阅鉴权、单聊文字、单聊图片、图文混排、群聊 @机器人、图片下载解密、30 秒心跳及逐帧回执；未发生连接接管，最终以 SIGTERM 手动停止。该结果只证明 E+ 协议，不代表毕昇身份、知识范围和队列已完成环境验收。

## 3. 客户测试环境必验

- [ ] 部署当前分支，执行数据库升级并确认 5 张 E+ 表在 MySQL 或客户实际数据库中存在，唯一键生效。
- [ ] 在 105 DM8 执行建表/唯一键检查；并发插入同一 `(tenant_id, bot_id, msgid)` 时只有一条成功。
- [ ] 启动两个 E+ Worker 副本，确认同一机器人只有一个连接；杀掉持有者，Redis 租约到期后另一副本接管。
- [ ] API、E+ Worker 分别部署或至少以独立容器运行；入站图片由 Worker 写入 MinIO，后续排队执行可以读取，不依赖 `/app/data`。
- [ ] 助手离线保存配置时不连接；助手上线且 E+ 启用后连接；助手下线、关闭配置或删除配置后断开。
- [ ] 使用已同步真实员工验证单聊文字、图片、图文混排和群聊 @机器人；库中不存在的员工固定回复「无权限使用」。
- [ ] 同一会话连续发送 3 条：后两条排队并自动续跑；第 4 条固定回复「消息处理中，请稍后再试」。
- [ ] 重投相同 `msgid`，确认不重复执行、不重复回复。
- [ ] 两个机器人绑定互斥空间；用户即使个人有其他空间权限也不能扩大机器人范围；零绑定不回退到助手原知识库。
- [ ] 执行中修改绑定：本轮继续用启动快照正常结束；下一轮使用新绑定；历史仍完整保留。
- [ ] 绑定空间存在 CUSTOM 文件权限时仍可问答；本期不做空间内单文件权限过滤。
- [ ] 断网、心跳丢失、普通重连、凭据轮换、外部客户端抢占连接均符合状态和退避策略。
- [ ] 长回答为累计全文刷新，不逐字发送；20,480 字节处截断并发结束帧；回复额度保留终态槽位。
- [ ] 查看日志，确认没有消息原文、Secret、aeskey 或完整带查询参数的 URL。
- [ ] 模型返回图片不作为本期验收项；机器人当前只发送文字内容。

## 4. 管理页手动验收

- [ ] 进入助手设置，看到 E+ 配置区域；Secret 只能填写/轮换，保存后不回显。
- [ ] 可选择多个本租户有效知识空间；管理员本人没有空间个人权限时仍可选择和保存。
- [ ] 跨租户、已删除、不存在的空间由后端拒绝。
- [ ] 可选 CA 上传、媒体域名白名单、启用开关、连接状态展示正确。
- [ ] 刷新页面后配置保持；中、英、日文案完整，无控制台错误。
- [ ] 既有内部助手文字、知识库、知识空间、图片、开放 API、分享页、上线、自动优化和评测主路径不受影响。

## 5. 发布判定

当前不可标记为生产验收通过。第 3 节的数据库、双 Worker、MinIO、真实身份和知识隔离项完成并留下日志位置后，才能把结论从 PARTIAL 改为 PASS。
