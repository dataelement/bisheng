# 模型展示名称修复验证

基线：`codex/dsh-enterprise-beta2@7374d699a6815cef7451bfa94e88deee9f2fcbb6`。本次修改 `DshModelService.list_models` 与管理端 `read_available_models`，通过同一格式函数优先读取管理员填写的展示名称；接口字段结构、路由 ID 和授权规则沿用现有实现。

## 验证结果

- `test_model_service.py`、`test_models_api.py`、`test_admin_service.py`：48 项通过，2 项 Redis 依赖用例按环境跳过，16 项外部数据库变体排除。
- 参数化用例覆盖管理员名称、首尾空白、空名称回退和提供方类型回退，并同时断言 Desktop 目录、管理接口名称及稳定 ID。
- 改动 Python 文件的 Ruff check/format 和架构守卫通过。
- MySQL/DM8 真库、Redis 集成、Desktop 真实登录与调用验收：`NOT_RUN`。
- 扩展尝试 `test_model_snapshot.py` 受本地 MinIO 等依赖缺失阻断，记为 `NOT_RUN`；目标展示名称路径由上述三组测试覆盖。

## 本地复现

从 `src/backend` 执行。共享测试 fixture 会预先替换 `bisheng.common.services` 包，因此单独运行这一组用例时先加载实际的 `metric_log.py`，再启动 pytest。测试环境包含项目所需的 pytest、pytest-asyncio、SQLModel、LangChain Core 和 OpenAI 依赖。

```python
import importlib.util
import sys
from pathlib import Path

import pytest

name = "bisheng.common.services.metric_log"
spec = importlib.util.spec_from_file_location(name, Path("bisheng/common/services/metric_log.py"))
module = importlib.util.module_from_spec(spec)
sys.modules[name] = module
spec.loader.exec_module(module)
raise SystemExit(pytest.main([
    "test/dsh/test_model_service.py",
    "test/dsh/test_models_api.py",
    "test/dsh/test_admin_service.py",
    "-q", "-k", "not external",
]))
```
