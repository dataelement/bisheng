# F050 E2E 覆盖报告

## 当前结论

**状态: PARTIAL**。自动化代码、静态门禁与本地可执行测试已通过；本机 `localhost:7860` 未启动，且没有专用 F050 E2E 部署凭据，因此 live API 与浏览器验收尚未执行，T035–T037 不能标记完成。

## 自动化结果

| 范围 | 结果 | 证据 |
|---|---|---|
| Client F048 adapter / draft / 页面契约 / 路由 / 抓取队列 | PASS | Node 环境定向回归：10 suites，31 tests |
| Frontend workspace ESLint | PASS | Platform、Client、UI、file-viewers 全部通过 `pnpm lint` |
| Frontend workspace TypeScript | PASS | Platform、Client、file-viewers 全部通过 `pnpm typecheck` |
| i18n parity + backend error-code coverage | PASS | `pnpm check-i18n` |
| Backend F050 focused regression | PASS | Permission/Knowledge/Channel 共 36 tests |
| Architecture guard | PASS | `scripts/arch-guard.sh` |
| Knowledge live E2E 收集 | SKIP | 3 tests；需 `F050_E2E=1` |
| Channel live E2E 收集 | SKIP | 3 tests；另需 `F050_E2E_CHANNEL_SOURCE_ID` |
| 新增 E2E Ruff | PASS | 2 files |

## Live E2E 文件

- `src/backend/test/e2e/test_e2e_f050_knowledge_permission_settings.py`
- `src/backend/test/e2e/test_e2e_f050_channel_permission_settings.py`

两个套件均使用至少 5 字符的 `e2e-f050-*` 前缀，并在模块前后只删除此前缀资源。默认安全跳过，不会连接或修改环境。

## 待执行命令

```bash
cd src/backend
F050_E2E=1 \
E2E_API_BASE=http://<dedicated-host>:7860/api/v1 \
E2E_ADMIN_PASSWORD='<password>' \
F050_E2E_CHANNEL_SOURCE_ID='<source-id>' \
uv run pytest \
  test/e2e/test_e2e_f050_knowledge_permission_settings.py \
  test/e2e/test_e2e_f050_channel_permission_settings.py -v
```

页面验收逐项记录在 `e2e-checklist.md`。live 环境执行完成并填写清单后，再更新本报告为 PASS 或 FAIL。
