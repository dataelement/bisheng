# E2E 验证与部署清单

状态：PARTIAL。本地后端/组件回归可重复执行；本轮没有部署新构建，116 只读观察不能视为新代码验收。真实 MySQL/DM8、FGA、worker、浏览器联调待专用环境验证。

## 可运行的只读 API 验收

`src/backend/test/e2e/test_e2e_tenant_model_metadata_read.py` 提供 5 条显式 opt-in 验收。默认跳过，不自动连接 116、登录、创建或清理数据；使用已有 E2E auth/响应 helper。因为完全只读、不创建数据，所以无需 setup/teardown 删除。

在升级后的专用测试租户预置 `e2e-tenant-metadata-` 前缀用户/模型和角色绑定、工具权限，并从该环境获得短期会话。配置 `E2E_API_BASE`（含 /api/v1）、`TENANT_METADATA_E2E=1`、`TENANT_METADATA_E2E_CASES`（JSON 对象）。token 只通过每个 case 的 `token_env` 引用环境变量传入，不存储到文件/报告。

五个 case 键：roles_super、roles_admin、assistant_user、tools_super、tools_user。每项包含 data_prefix、token_env；超管还需 headers_env 指向 JSON 请求头环境变量，包含已确认所选租户的 X-Management-Tenant 和对应管理 Cookie（仅管理 Cookie，由 helper 与登录 Cookie 合并，不替换认证）。不得通过伪造目标头绕过服务端选择协议。

- roles_*：department_id、user_id、role_ids；roles_super 另含 issue_reasons。准备共享角色、跨存储/定义范围的已有授权及缺失定义绑定；前两类继续生效，缺失定义仅超管诊断。
- assistant_user：online_model_ids，按期望默认及分组顺序列出全部已配置在线候选；模型名字必须带测试前缀。已选项保留、离线/撤销和错误展示另见 UI 清单。
- tools_*：visible_tool_type_ids，匹配完整工具类型可见列表（含预置工具）；分别提供超管子租户与普通用户的预期集合。

从 backend 执行：`.venv/bin/pytest test/e2e/test_e2e_tenant_model_metadata_read.py -q`。未提供环境时本轮实测 5 skipped，不能计为通过。明确拒绝与更新状态等写请求仅在后续专用环境验收，不发送到本轮只读 116。

## 页面及写请求验收

- [ ] AC-01/02：超管选择子租户，合法共享/自有角色显示；既有跨范围绑定按 3.0.0 兼容策略继续显示，缺失定义标记未生效及准确原因；普通管理员响应和页面无异常细节。切换目标不能残留另一租户成员。
- [ ] AC-03：运行容器工具构造器使用正式 tenant_id；超管子租户及普通用户列表分别符合权限集合，身份一致性检查保持。
- [ ] AC-04：助手配置包含自有和 Root 共享模型；新节点选择默认、已有节点保持选择；模型下线、共享撤销、配置引用失效均不回退全模型。模拟失败显示错误及重试；延迟旧响应后切租户不串候选。
- [ ] AC-05：子租户 Root 共享行无更新状态按钮，提示 Root 操作；直接 POST /llm/verify 返回 19801 且不触发模型调用。Root/Root、子租户/自有模型成功；普通用户无状态更新权限。
- [ ] AC-06：空 schema 文件弹窗中新建空间字段，确认后显示加工任务，任务完整成功且 schema 可读后才进入赋值；刷新文件后值保持。
- [ ] AC-06/07：添加已有字段，修改字符串/数字/时间；删除当前文件值不删除空间定义或其他文件值。重复字段、非法名字不提交，保存失败及明确创建拒绝保留可修改草稿。
- [ ] AC-07：创建超时重试使用同一幂等键；加工失败保留字段草稿；切文件、空间、租户后旧预检不继续确认，旧写入响应不关闭新弹窗或调用新目标回调。
- [ ] AC-08：只读重新检查 3547 两条失败出站任务及源输入保护。完整成功后自然释放的场景在专用测试数据验证；不删除 3547 或恢复现场任务。

自动化覆盖与已知基线限制见 validation.md；现场具体编号及恢复核查见 116-readonly-investigation.md。
