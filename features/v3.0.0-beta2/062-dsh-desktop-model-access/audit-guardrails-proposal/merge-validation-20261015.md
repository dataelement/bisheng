> 来源分支历史归档，非 work-110 本轮验收；本分支适配见 work110-port.md。

# 2026-10-15 分支合并验证

## 范围

目标为服务端 `feat/3.0.0-dsh-audit`。先将本地审计分支快进到远端已有提交 `c6d00aa41e44f093c23f99a5b57f2a57530bc65c`，再合并最新 `origin/feat/bisheng-work-103=448f05d9842e67c0ceb192d85d9814b14785f88f`。保留审计实现和远端已有安装策略；新增工作台市场及其接口、测试和三语文案。无文本冲突，不覆盖任一父分支的整文件。

本次仅合并、验证和推送服务端审计分支，不修改客户端仓库，不操作 109 的容器、数据库或审计模式，不代表镜像已重建或部署完成。

## 迁移头修复

合并前离线单头测试实际失败，Alembic 报两个 head：`merge_dsh_heads`、`f065_dsh_install_policy_default_off`。新增 `v3_0_0_f065_merge_dsh_audit_heads.py`，`down_revision` 精确引用这两个已发布节点；`upgrade()` / `downgrade()` 均为空，不做 DDL/DML，不改已有迁移父节点，不使用 stamp 或跳过迁移。

修复后 `alembic heads` 仅返回 `f065_merge_dsh_audit_heads`。新增四项测试验证父节点、从两个旧 head 到新 head 的迁移图以及空操作主体；结合原单头守卫通过。本验证不连接真实数据库，不等同完整新装/升级或 DM8 验收。

## 实际检查

| 检查 | 结果 |
|---|---|
| 后端组合测试 | 180 passed、2 skipped、1 deselected；覆盖单头/合并迁移、模型审计、DSH runtime/SQL、vision、完整 dsh_market 组合 |
| 前端相关 Vitest | 6 文件、34 项通过；包含市场、审计 API/页面、请求兼容和导航 |
| 全前端 typecheck | 通过；Platform 536 strict files、Client 1359 strict files、file-viewers |
| check-i18n / locales:check | 均通过；自动合并后的三语 JSON 无重复键，生成件一致，未手改生成文件 |
| Platform 构建 | 通过，8285 modules，18.14s；保留既有 ace/eval/大 chunk 警告 |
| Ruff / 架构守卫 / 暂存 diff-check | 修改范围通过；无冲突标记，不修改既有迁移历史 |

后端组合命令（在 `src/backend`，使用已安装依赖和测试 mock）：

```sh
python -m pytest test/database/test_alembic_single_head.py \
  test/database/test_dsh_audit_merge_revision.py test/dsh/test_model_audit*.py \
  test/dsh/test_operations_runtime.py test/dsh/test_sql_portability.py \
  test/dsh/test_vision.py test/dsh_market -m 'not e2e' -q
alembic heads
```

两个 skip 为当前环境无真实 DM 编译器；deselected 为显式启用的 HTTP E2E。本次未重跑全 DSH/全量 lint，也未以定向通过覆盖此前记录的既有门禁失败、正式 Electron/Gateway/供应商或压力验收缺口。后续部署须先确认新镜像实际包含该单头合并迁移，再重新做环境 preflight。
