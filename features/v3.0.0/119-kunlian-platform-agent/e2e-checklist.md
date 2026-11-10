# 平台 Agent Mock 联验清单

状态：NOT_RUN，待执行。正常 API／Broker／Worker 的专用账号验收尚未执行；本地服务是否启动不等于此清单已通过。

## 环境与账号

- 默认启动即启用 Mock。已有用户通过本地身份、租户及 Workflow 资格校验后，可直接选择通用 echo 和故障样例，无需添加平台配置或手填用户映射。当前运行的旧 API／Worker 须重启加载新默认值，刷新画布后可见。
- 正式执行本验收清单时使用专用测试租户。为覆盖 A／B 授权差异、私有样例和空目录，准备两个本地自然人账号并按下方可选映射指定 A／B。A 可以创建、编辑、发布和管理测试工作流权限，B 为普通使用者。
- API、Worker 使用相同 Workflow 设置，MySQL 或 DM8、Redis、OpenFGA、MinIO 与既有 Workflow Worker 就绪。
- 以下仅为专项验收的可选配置，合并到后台系统配置。非空映射中未登记的用户继续拒绝；省略整个配置时默认使用通用 B 样例。本轮没有修改实际运行配置。

```yaml
workflow:
  platform_agent:
    mode: mock
    connection_id: kunlian
    policy_revision: mock-v1
    invoke_timeout_seconds: 5
    max_payload_bytes: 1048576
    mock_subjects:
      "<TENANT_ID>:<AUTHOR_USER_ID>": A
      "<TENANT_ID>:<RUNNER_USER_ID>": B
      "<OTHER_TENANT_ID>:<OTHER_USER_ID>": C
```

## 正常 API 与 Worker

基础手动验证时选择「通用问答示例 (模拟)」→ v1，query 填入任意文本，调用返回模拟回显；v2 的输入改为 question、输出改为 reply，用于版本不兼容验证。「失败与超时示例 (模拟)」的各版本用于错误、超时、错误输出、非终态及版本不符验证。私有样例仅在专项 A 映射下可见。

若旧进程还未加载 Mock 名称更新，请重启本地后端；前端刷新后应先显示“模拟数据”，再从后端加载目录和版本。多租户身份未就绪时应明确提示，不应静默显示两个空下拉框。此步骤尚未记为真实浏览器通过。

脚本：`src/backend/test/workflow/test_platform_agent_e2e.py`。

执行前通过进程环境提供 `F119_MOCK_E2E=1`、`E2E_API_BASE`、`F119_AUTHOR_USERNAME`、`F119_AUTHOR_PASSWORD`、`F119_RUNNER_USERNAME`、`F119_RUNNER_PASSWORD`、`F119_TENANT_ID`、`F119_USE_MODEL_KEY` 和 `F119_RUN_ID`。密码不写入仓库。使用权限模型只授予 B 使用资格，不应包含编辑资格；运行 ID 为 8 至 40 位字母、数字或连字符。

```bash
cd src/backend
uv run pytest test/workflow/test_platform_agent_e2e.py -v -rs
```

脚本使用正常登录、目录、版本、保存、发布、授权和开放运行入口；SQL、权限引擎和队列不替换为内联调用。只清理 `e2e-f119-<RUN_ID>` 精确名称、指定租户和所有者一致的测试工作流，不清理用户或租户。脚本未运行不计业务验收通过。

- [ ] AC-03：A 创建并保存示例，GET 重开内容与保存一致。
- [ ] AC-08：A 发布 V1，再保存 V2 草稿，已发布图和运行仍使用 V1。
- [ ] AC-10、AC-13：B 经真实 Worker 运行，输出 `F119 Mock / B`；昆联侧身份仍是 Mock。
- [ ] AC-15：A 发布仅 A 可用的 `mock:private`，B 本地有 use 但外部 Mock 拒绝，事件保留 10555，不出现成功输出。
- [ ] AC-20、AC-23：记录 Session 和本次执行标识，确认模拟来源、固定版本及 Mock 返回的运行标识。
- [ ] AC-22：B 没有编辑权限，资源目录接口拒绝；原普通工作流仍能运行。

## 浏览器

- [ ] AC-01、AC-02：Mock 开启后显示“平台 Agent（模拟数据）”；关闭后不能新增。空目录与查询失败提示不同。
- [ ] AC-03、AC-04：导入 `mock-workflow.example.json`，保存重开，固定版本及对象、数组、0、false、null 保持原类型。变量试运行输入使用 JSON，字符串加双引号。
- [ ] AC-05：将 echo V1 切为 V2，修正 query→question、answer→reply；旧输入和下游字段未修复时阻止发布与试运行。
- [ ] AC-09、AC-14、AC-16、AC-18：分别使用 disabled、bad-output、timeout、running 场景，失败不推进下游，不自动重发；超时说明远端结果未知。
- [ ] AC-11、AC-12：A 发布、B 运行；切换用户或租户后目录不沿用上一个人的结果。身份或本地权限失效后拒绝新发送。
- [ ] AC-19：在 Mock timeout 场景停止；迟到结果不写变量、不触发下游；新一次运行不出现旧运行的状态或事件。
- [ ] AC-20、AC-21：运行界面展示状态、版本、模式及可用运行标识；错误不出现访问令牌、密钥或认证报文。

真实昆联接口、真实身份审计及 MySQL／DM8 多实例锁语义继续按 T048—T050 单独登记，不能用以上 Mock 结果替代。
