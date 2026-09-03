# E2E 验证清单: F051 知识库列表动作权限懒加载

**测试环境**: 部署 F051 后的专用测试环境
**自动化入口**: `F051_E2E=1 E2E_API_BASE=http://<host>:<port>/api/v1 uv run pytest test/e2e/test_e2e_f051_knowledge_list_action_lazy_load.py -v`
**前置条件**: 至少准备文档库、QA 库各一个，并准备仅 visible、具备 edit、具备 manage_permission 的账号。

## API 自动化覆盖

- [ ] AC-01/02/04：文档库与 QA 库 `action=visible` 返回行的 `actions` 均严格为 `["visible"]`。
- [ ] AC-03/14：`action=use` 保持原资源选择结果，返回行仍只有 `visible`。
- [ ] AC-05/07：对列表中的单个资源调用 `my-permissions` 可取得当前有效 actions，列表响应不随之扩张。

## Platform 前端

### AC-05/06/07：打开菜单后加载当前行动作

- [ ] 以普通用户进入 `/filelib`，分别切换文档库与 QA 库。
- [ ] 打开浏览器 Network，刷新列表；首屏不得出现 `my-permissions` 请求。
- [ ] 点击一个普通行的三点按钮；出现“正在加载可用操作”，且最多产生一个该资源的 `my-permissions` 请求。
- [ ] 请求成功后，只显示该用户获准的设置、删除、权限管理项。
- [ ] 具备 `create_knowledge` 且资源为 Published 时，复制项仍独立显示。

### AC-08/09/10：关闭、切换与失败关闭

- [ ] 加载期间关闭 A 行菜单；响应完成后菜单不得自动重开。
- [ ] 快速依次打开 A、B 行；B 行不得显示 A 行的 actions。
- [ ] 模拟 `my-permissions` 失败；当前菜单关闭，显示权限校验失败提示，且不出现管理操作。
- [ ] 重新打开同一行；允许重试，不得因失败结果伪造授权。

### AC-12/15：租户与处理中状态

- [ ] 使用另一租户账号访问同一资源 ID；不得展示或执行跨租户操作。
- [ ] 复制中或未发布行保持 spinner/禁用状态，点击不得发起 `my-permissions`。

## 回归检查

- [ ] 管理员也在打开三点菜单后才请求动作，设置/删除/权限管理仍可用。
- [ ] 文档库与 QA 库详情跳转、复制、设置、删除、权限管理均执行服务端最终鉴权。
- [ ] 搜索、游标加载更多、`action=use` 选择器资源集合无变化。
- [ ] 页面无新增 console error；三语 loading/empty 文案正确。
