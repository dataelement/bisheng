# F079 验证与交付清单

## 离线自动化

`test/knowledge/test_knowledge_space_info_optimization.py` 覆盖 AC-01～06，包括真实 Service 调用链、普通 actor、未加入的部门授权、历史申请状态、私密/未发布拒绝、创建者/超管、下载开关和阶段异常。

ASGI 用例运行真实路由及 Service，依赖和 I/O 使用替身；负向用例断言路由抛出的原始业务错误。它们不证明 JWT、生产异常中间件、真实 OpenFGA 或达梦性能。

## 指定测试环境 API 验收（待部署后执行）

套件：`test/e2e/test_e2e_cofco_space_info.py`，复用共享认证 header 与响应断言 helpers。仅 GET，使用预置测试数据，无创建/清理动作。

启用条件：已部署 F079、显式指定 `E2E_API_BASE`、`COFCO_INFO_E2E=1`，并通过临时环境变量提供 `COFCO_INFO_E2E_CASES` JSON 及其引用的短期 token。凭据不写入仓库或报告。未设置开关时明确跳过。

case map 必须包含以下键：member、department_grant、pending_visible、rejected_visible、preview_not_joined、preview_pending、preview_rejected、creator、super_admin_not_joined、private_denied、cross_tenant_denied。

每个 case 的字段：

```json
{
  "space_id": 303,
  "data_prefix": "e2e-cofco-info-",
  "token_env": "COFCO_INFO_MEMBER_TOKEN",
  "expected_button_actions": ["visible"]
}
```

预期访问结果、状态和身份由套件固定，case map 只选择测试资源及短期凭据，不能通过配置放宽断言。普通可访问用例（含 pending_visible/rejected_visible）预期 subscribed；preview_* 分别预期未加入、审批中、拒绝；super_admin_not_joined 用超管身份且预期 not_subscribed。

所有被访问空间须由操作者**提前确认已发布**；`/info` 的既有重建副作用未改变，不可对任意空间盲测。普通身份用例会先检查 `/user/info` 的管理员标志；私密空间固定断言 18040，跨租户隐藏空间固定断言 18000。不同错误结果须调查既有边界，不能直接放宽测试。

从 `src/backend` 运行：

```bash
uv run pytest test/e2e/test_e2e_cofco_space_info.py -v
```

## 浏览器验收（待部署后执行）

- [ ] AC-01/04：普通成员及仅部门授权用户打开分享链接，进入空间；上传、编辑等按钮仍由 my-permissions 控制。
- [ ] AC-02：具备可见权限但历史申请仍 pending/rejected 的用户，详情及广场显示已加入，申请记录未被本次 GET 改写。
- [ ] AC-03：无权限者进入已发布公开/审批空间，展示申请页及准确申请状态；私密或未发布空间继续拒绝。
- [ ] AC-04：超管能打开无真实授权的空间，广场及个人加入列表不把全部空间标为已加入；创建者正常进入。
- [ ] AC-05：Catalog 禁用下载时隐藏下载入口；启用时保持原体验；设置页权限摘要正常。

## 性能验收（待部署后执行）

- 同一普通账号、同一已发布空间、相同并发背景分别保留升级前与升级后样本。
- 首开单列，连续访问建议不少于 30 次，统计中位数、P95 和最大值；后台负载变化一并记录。
- 对照 `domain=knowledge_space_info` 的各阶段及 HTTP 总耗时；Service total 不覆盖依赖初始化和序列化。
- 普通有效成员预期仅一次入口 visible；无成员记录的可访问者仍可有一次 manage_permission；超管仍可能另查真实加入可见性。
- 不把七轮展开消除推算成固定耗时下降，不把客户 `/children` SQL A/B 的收益用于 `/info`。
