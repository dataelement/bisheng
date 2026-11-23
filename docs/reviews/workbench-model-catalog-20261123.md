# Code Review Report

**Feature**: 工作台候选模型与系统模型设置保持一致
**Review scope**: 已确认缺陷的 hotfix；候选集合不受 DSH 开关影响
**Base branch**: origin/feat/3.1.0-beta2（23c82f7769）
**Changed files**: 7（不含本报告）

## Summary

| Dimension | High | Medium | Low | Status |
|-----------|------|--------|-----|--------|
| Boundary Conditions | 0 | 0 | 0 | PASS |
| Permission & Auth | 0 | 0 | 0 | PASS |
| Concurrency Safety | 0 | 0 | 0 | PASS |
| Information Leakage | 0 | 0 | 0 | PASS |
| Test Coverage | 0 | 0 | 0 | PASS |
| Code Style | 0 | 0 | 0 | PASS |
| Docs Sync (design.md) | 0 | 0 | 0 | PASS |

## 核对结果

- 候选集合统一取 `LLMService.aget_online_chat_models()`，与设置页所列在线对话模型使用相同的本租户/Root 实际共享来源；配置中的 `models` 只补充展示元数据。
- 超管展示合法候选的全集，Root 与子租户均不消费个人积分政策生成列表；普通用户仍按平台可见范围过滤，不接受伪造的跨租户管理范围。
- 空集合及不可见默认模型沿原投影规则处理；同名模型保留不同 ID 和提供方信息；投影不修改原始配置。
- 没有可见范围记录时，设置接口与候选列表均按默认全员可见解释，与 DSH 开关无关。已有显式限制保留。
- 移除不再调用的 DSH 专用候选和投影函数，没有新增表、迁移、依赖或异步写入。
- 所属 feature 的 design.md 已补充本次用户确认的候选规则及继承配置不能作为白名单的原因。

## Validation

在本开发工作区使用仓库现有 Python 3.11 虚拟环境和 beta2 自带的临时配置/密钥引导运行：

```sh
env -u config PYTHONPATH="$PWD" /Users/zhangguoqing/works/bisheng/src/backend/.venv/bin/python -m pytest \
  test/dsh/test_model_display_catalog.py \
  test/dsh/test_model_visibility_without_dsh.py \
  test/llm/test_user_model_visibility_execution.py \
  test/llm/test_workbench_model_providers.py \
  test/dsh/test_chat_credits.py -q --disable-warnings --tb=short
```

结果：**39 passed**。已对本轮 Python 文件运行 `ruff format`、`ruff check`；对变更路径运行 `scripts/arch-guard.sh`，无违规；`git diff --check` 通过。

## 验证边界

本地回归使用模拟目录/模型与 SQLite 策略数据，未部署至 116，未执行真实供应商对话或生产数据库/DM8 集成验证。本次没有修改跨租户个人策略执行、DSH 计费身份及账本规则；前期排查出的 24006/26117 执行问题不在本次“候选列表一致性”修复的完成声明内。

## Overall: PASS
