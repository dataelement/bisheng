# F117 部署后只读验收

状态：待执行。只对明确选定、已升级的专用测试部署运行；本次未部署，不使用 109 中粮结果代替主线验收。

## 自动化

`test/e2e/test_e2e_space_info.py` 默认跳过。使用已有、名称以 `e2e-space-info-` 开头且 state=1 的空间和临时 JWT；套件只 GET，不创建/删除数据，因此不运行写入式 setup/cleanup。未上架广场的预览 fixture 也必须是 state=1，避免触发旧有重建逻辑。

运行前设置：

```bash
export E2E_API_BASE='https://<test-host>/api/v1'
export SPACE_INFO_E2E=1
# SPACE_INFO_E2E_CASES 由操作人提供 JSON；各 token 由 token_env 指定的临时环境变量提供。
uv run pytest test/e2e/test_e2e_space_info.py -v
```

JSON 按以下 case_name 提供对象，每项含 `space_id`、`tenant_id`（当前身份预期租户）、`data_prefix`、`token_env`；成功项另含 `expected_user_role`（可为 null）、`expected_button_actions`。不得把凭据提交到仓库或报告。

| case_name | 预期 |
|---|---|
| member / department_grant | 普通成员或无成员记录的授权用户，visible、subscribed |
| pending_visible / rejected_visible | 历史申请中/拒绝但有有效授权，visible、subscribed；记录不被改写 |
| preview_not_joined / stale_active_preview | 无有效授权，空 actions、not_subscribed、空角色 |
| unreleased_preview | is_released=false 的公开/审批分享预览，空 actions、not_subscribed |
| preview_pending / preview_rejected | 不可见，分别 pending/rejected |
| creator | visible、subscribed、creator |
| super_admin_not_joined | 可进入但无个人授权，not_subscribed |
| private_denied / cross_tenant_denied | 分别返回 18040 / 18000 |

跨租户拒绝 fixture 的资源属于另一租户；case.tenant_id 仍是请求身份当前租户。失败项不检查资源内容。

## 手动与观测

- [ ] AC-01：普通用户从分享入口进入已授权空间；详情、设置及编辑/删除/分享菜单权限与 my-permissions 一致。
- [ ] AC-02：有部门/直接授权且历史申请中/拒绝时进入内容页；权限撤回后展示加入页，仍可再次申请。核对成员/审批记录未被详情读取改写。
- [ ] AC-03：未上架广场的公开/审批分享链接可预览，私有和跨租户拒绝正确。
- [ ] AC-04：创建者、成员、管理授权无成员、超管未加入，角色/统计/部门/标签正常。
- [ ] AC-05：按同一 trace 核对 knowledge_space_info 的九阶段、total 及失败阶段；与 HTTP/gateway 时间分别比较，不叠加身份解析耗时。
- [ ] AC-06：managed、加入/退出和文件下载行为正常；在 MySQL/DM8 的正式回归环境分别验收。

不预设毫秒或提速倍数；使用相同账号、空间、数据和负载比较升级前后。
