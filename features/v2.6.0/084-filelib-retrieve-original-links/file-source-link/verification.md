# 验证记录

- Date: 2026-09-08
- Status: MANUAL_VERIFY_REQUIRED
- 本地实现与自动化验证通过；未部署、未联调真实 MinIO。

## 验收覆盖

| Acceptance | Evidence | Status |
|---|---|---|
| AC-01 | HTTP 路由、响应结构、正整数参数、无需检索依赖测试 | PASS |
| AC-02 | Token 拒绝、external_id 上下文、空间/文件权限拒绝且不签名 | PASS |
| AC-03 | 真实入口解析器配合替身 Repository 验证普通文件、有效发布引用、无效引用 | PASS |
| AC-04 | 公网 Origin、空值回退、保留编码查询、非法 Origin 拒绝；配置保存和缓存失效 | PASS |
| AC-05 | no-store、7 天参数、既有对象缺失/签名失败降级回归 | PASS |
| 生产链路 | 真实 Developer Token、数据库权限、MinIO 存储及公网代理 GET | MANUAL_REQUIRED |

## 自动化证据

工作目录：`src/backend`；解释器：项目 `.venv`，Python 3.10.19。

```bash
./.venv/bin/python -m pytest \
  test/open_endpoints/test_filelib_file_source_url.py \
  test/open_endpoints/test_filelib_retrieve_source_service.py \
  test/open_endpoints/test_filelib_external_user_context.py \
  test/knowledge/test_knowledge_space_chat_service_retrieve.py \
  test/knowledge/test_chunking_config.py -q
```

结果：92 passed，8 个依赖告警，4.21 秒。HTTP 集成覆盖真实 DI、Service 和解析器；外部存储、配置、权限及数据库使用替身，不代表真实存储已联通。

测试先行：新接口测试最初因 Service 不存在收集失败；Origin 测试最初 10 项因缺少构造参数失败。实现后转绿。首次相关回归 90 passed、2 failed，确认旧 retrieve 测试夹具未同步当前依赖后补齐；最终结果如上。

Ruff：新 Service、共享 source Service 和两个 source 测试文件完整 check 通过，format --check 为 4 files already formatted。DI、Endpoint、Schema、external_user_context 测试的 E9/F/I 检查通过；两个大型既有配置文件的 E9/F 检查通过。`git diff --check` 通过。

架构守卫：对本次 7 个生产 Python 文件分别执行 `bash scripts/arch-guard.sh <file>`，无 VIOLATION。settings.py 有 RULE-7 既有告警；对 HEAD 文件只计数核实已有 1 处匹配，本次未新增敏感字面量。

## 待部署人工验证

1. 在后台保存文件代理 Origin；确认旧 portal_base_url 不含页面路径。
2. 使用允许新路由的 Developer Token 请求接口，分别验证 Token 用户与 external_id 用户；无权用户不能获得签名。
3. 用有权限普通文件和有效引用文件的 ID 获取 URL，确认非空、`X-Amz-Expires=604800`，直接 GET 内容为目标原文件。
4. 确认新接口和 retrieve 返回相同 Origin；Nginx 保持签名路径/查询串，并向 MinIO 恢复 sharepoint Host。
5. 核验后端 sharepoint 连通及 bucket 根路径 region 请求；只改公开地址不解决该链路。

未运行生产数据库、真实 MinIO、生产 Nginx 或跨数据库端到端验证；无 Schema/数据库方言改动。未提交、未部署，保留用户原有工作区改动。
