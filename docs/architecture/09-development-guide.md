# 开发指南

本文档面向 BiSheng 项目的开发者，涵盖环境搭建、服务启动、新模块开发约定、工作流节点扩展、API 端点添加、测试和代码风格规范。后端使用 Python 3.10.14 + uv 管理依赖（2.4.0 版本已从 Poetry 迁移到 uv），前端使用 React + TypeScript + Vite。

## 环境搭建

### 后端环境

```bash
# 1. 创建 Python 3.10.14 虚拟环境（必须使用此版本）
conda create --name BiShengVENV python==3.10.14
conda activate BiShengVENV

# 2. 安装后端依赖（使用 uv，lockfile 为 uv.lock）
cd src/backend
uv sync --frozen --python $(which python)
```

`uv sync` 会在 `src/backend/.venv/` 下创建虚拟环境并安装全部依赖。后续启动服务均通过 `.venv/bin/` 下的可执行文件调用。

### 前端环境

```bash
# Platform 前端（主应用）
cd src/frontend/platform
npm install

# Client 前端（客户端嵌入应用）
cd src/frontend/client
npm install
```

### 存储服务

存储服务通过 Docker Compose 启动，然后停止与本地开发冲突的容器：

```bash
cd docker && docker compose -p bisheng up -d
docker stop bisheng-backend bisheng-backend-worker bisheng-frontend
```

## 服务启动

### 后端 API 服务

```bash
cd src/backend
.venv/bin/uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log
```

本地开发建议使用 `--workers 1` 以便调试。生产环境的 Docker 容器默认使用 `--workers 8`。

### Celery Workers

每个 Worker 需要独立的终端窗口：

```bash
# 知识库任务 Worker（文档解析、Embedding 生成、向量写入）
.venv/bin/celery -A bisheng.worker.main worker -l info -c 20 -P threads -Q knowledge_celery -n knowledge@%h

# 工作流任务 Worker（工作流 DAG 执行）
.venv/bin/celery -A bisheng.worker.main worker -l info -c 100 -P threads -Q workflow_celery -n workflow@%h

# 定时任务调度器（遥测统计、情报同步）
.venv/bin/celery -A bisheng.worker.main beat -l info
```

### Linsight Worker（可选）

灵思 Agent 框架使用独立的 Python 进程，不走 Celery 队列：

```bash
.venv/bin/python bisheng/linsight/worker.py --worker_num 4 --max_concurrency 5
```

### 前端开发服务器

```bash
cd src/frontend/platform
npm start -- --host 0.0.0.0
```

Vite 开发服务器运行在 3001 端口，自动将 `/api/` 和 `/health` 请求代理到后端 `localhost:7860`。文件服务路由（`/bisheng`、`/tmp-dir`）代理到 MinIO。

## 新模块开发约定

后端遵循领域驱动设计（DDD）模式。新增业务模块时，按以下目录结构组织代码。

### 目录结构

```
src/backend/bisheng/<module_name>/
├── api/                              # API 层
│   ├── router.py                     #   路由注册（创建 APIRouter）
│   ├── dependencies.py               #   依赖注入（可选）
│   └── endpoints/                    #   端点实现
│       └── <module_name>.py          #     CRUD 端点函数
│
└── domain/                           # 领域层
    ├── models/                       #   领域模型（ORM 实体）
    ├── schemas/                      #   Pydantic 数据传输对象
    ├── services/                     #   领域服务（核心业务逻辑）
    └── repositories/                 #   仓储层（可选）
        ├── interfaces/               #     仓储接口定义
        └── implementations/          #     仓储实现
```

### 步骤

1. **创建模块目录**：在 `src/backend/bisheng/` 下创建模块目录，包含 `api/` 和 `domain/` 子目录。

2. **定义路由**：在 `api/router.py` 中创建 `APIRouter`，设置路由前缀和标签：

```python
from fastapi import APIRouter
from bisheng.<module_name>.api.endpoints.<module_name> import router as module_router

router = APIRouter(prefix='/<module_name>', tags=['<ModuleName>'])
router.include_router(module_router)
```

3. **注册到全局路由**：在 `src/backend/bisheng/api/router.py` 中导入并注册路由：

```python
from bisheng.<module_name>.api.router import router as module_router

router.include_router(module_router)  # 注册到 v1 路由
```

4. **实现业务逻辑**：遵循调用链路 `Router -> Endpoint -> Service -> Repository -> ORM`。较简单的模块可省略 Repository 层，在 Service 中直接调用 DAO。

### 调用链路

```
api/endpoints/<module_name>.py    ← 接收请求，校验参数，调用 Service
         |
         v
domain/services/<service>.py      ← 业务逻辑编排，事务控制
         |
         v
domain/repositories/impl/<repo>.py  ← 数据访问（或直接调用 database/models/ 中的 DAO）
         |
         v
database/models/<model>.py        ← SQLModel ORM，DAO 方法（sync get_xxx / async aget_xxx）
```

## 新工作流节点开发

工作流引擎基于 LangGraph，支持 14 种节点类型。扩展新节点需要修改三个位置。

### 步骤

1. **创建节点目录**：在 `src/backend/bisheng/workflow/nodes/` 下创建节点子目录：

```
src/backend/bisheng/workflow/nodes/my_node/
├── __init__.py
└── my_node.py
```

2. **实现节点类**：继承 `BaseNode`（`src/backend/bisheng/workflow/nodes/base.py`），实现 `_run` 抽象方法：

```python
from bisheng.workflow.nodes.base import BaseNode

class MyNode(BaseNode):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 从 self.node_data 中提取节点配置参数
        # 将处理后的参数存入 self.node_params

    def _run(self, unique_id: str):
        """
        节点执行逻辑。

        参数:
            unique_id: 本次执行的唯一标识

        行为:
            - 通过 self.graph_state.get_variable() 读取上游节点变量
            - 执行业务逻辑
            - 通过 self.graph_state.set_variable() 写入输出变量
            - 通过 self.callback_manager 发送事件（on_node_start, on_node_end 等）
        """
        pass
```

`BaseNode` 构造函数接收以下关键参数：
- `node_data: BaseNodeData` -- 节点配置数据（类型、参数、描述）
- `workflow_id: str` -- 所属工作流 ID
- `user_id: int` -- 执行用户 ID
- `graph_state: GraphState` -- 全局变量池，管理节点间数据流
- `target_edges: List[EdgeBase]` -- 出边列表
- `max_steps: int` -- 最大执行步数（默认 50）
- `callback: BaseCallback` -- 回调管理器，支持流式输出

3. **注册节点类型枚举**：在 `src/backend/bisheng/workflow/common/node.py` 的 `NodeType` 枚举中添加新类型：

```python
class NodeType(Enum):
    # ... 现有类型
    MY_NODE = "my_node"
```

4. **注册节点工厂映射**：在 `src/backend/bisheng/workflow/nodes/node_manage.py` 的 `NODE_CLASS_MAP` 中添加映射：

```python
from bisheng.workflow.nodes.my_node.my_node import MyNode

NODE_CLASS_MAP = {
    # ... 现有映射
    NodeType.MY_NODE.value: MyNode,
}
```

### 现有节点类型参考

| 类型 | 枚举值 | 说明 |
|------|--------|------|
| `START` | `start` | 工作流起始节点 |
| `END` | `end` | 工作流终止节点 |
| `INPUT` | `input` | 用户输入节点 |
| `OUTPUT` | `output` | 结果输出节点 |
| `FAKE_OUTPUT` | `fake_output` | 伪输出节点 |
| `LLM` | `llm` | 大语言模型调用 |
| `CODE` | `code` | 代码执行节点 |
| `CONDITION` | `condition` | 条件分支判断 |
| `KNOWLEDGE_RETRIEVER` | `knowledge_retriever` | 知识库向量检索 |
| `QA_RETRIEVER` | `qa_retriever` | 问答检索 |
| `RAG` | `rag` | 检索增强生成 |
| `TOOL` | `tool` | 工具调用 |
| `AGENT` | `agent` | Agent 智能体 |
| `REPORT` | `report` | 报告生成 |

## 新 API 端点开发

### 步骤

1. **创建端点文件**：在对应模块的 `api/endpoints/` 目录下创建文件，定义路由和处理函数：

```python
from fastapi import APIRouter, Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200

router = APIRouter(prefix='/my-resource', tags=['MyResource'])


@router.get('/', response_model=UnifiedResponseModel)
async def list_resources(login_user: UserPayload = Depends(UserPayload.get_login_user)):
    """获取资源列表。"""
    # login_user 包含: user_id, user_name, user_role
    # login_user.is_admin() 判断是否管理员
    # login_user.access_check(owner_id, target_id, access_type) 检查资源权限
    data = []
    return resp_200(data=data)
```

2. **认证依赖注入**：通过 `UserPayload = Depends(UserPayload.get_login_user)` 获取当前登录用户。`UserPayload` 从 JWT Cookie 中解析用户身份，提供以下属性和方法：

| 属性/方法 | 类型 | 说明 |
|----------|------|------|
| `user_id` | `int` | 用户 ID |
| `user_name` | `str` | 用户名 |
| `user_role` | `List[int]` | 用户角色 ID 列表 |
| `is_admin()` | `bool` | 是否管理员 |
| `access_check(owner_id, target_id, access_type)` | `bool` | 资源权限检查 |

WebSocket 端点使用 `UserPayload.get_login_user_from_ws` 变体。

3. **统一响应格式**：所有 API 返回 `UnifiedResponseModel`，通过辅助函数构造：

```python
from bisheng.common.schemas.api import resp_200, resp_500

# 成功响应
return resp_200(data={"id": 1, "name": "test"})
# 返回: {"status_code": 200, "status_message": "SUCCESS", "data": {...}}

# 错误响应
return resp_500(code=500, message="操作失败")
# 返回: {"status_code": 500, "status_message": "操作失败", "data": null}
```

4. **注册路由**：在模块的 `api/router.py` 中包含端点路由，然后在 `src/backend/bisheng/api/router.py` 全局路由中注册。

### 错误码规范

错误码体系定义在 `src/backend/bisheng/common/errcode/` 和 `src/backend/bisheng/api/errcode/` 中。错误码为 5 位整数，前 3 位标识模块，后 2 位标识具体错误。继承 `BaseErrorCode` 可定义模块专属错误码，支持三种输出格式：

- `return_resp()` -- HTTP JSON 响应
- `to_sse_event()` -- SSE 事件流
- `websocket_close_message()` -- WebSocket 关闭消息

## 测试

### 运行测试

```bash
cd src/backend

# 运行全部测试
.venv/bin/pytest test/

# 运行单个测试文件
.venv/bin/pytest test/test_knowledge.py

# 运行单个测试用例
.venv/bin/pytest test/test_knowledge.py::test_fn

# 按关键字筛选测试
.venv/bin/pytest test/ -k "keyword"
```

### 测试文件位置

测试代码位于 `src/backend/test/` 目录。测试文件命名遵循 `test_<module>.py` 约定。

## 代码风格

### 后端

使用 Black 格式化和 Ruff 代码检查：

```bash
cd src/backend

# 代码格式化
.venv/bin/black .

# 代码检查与自动修复
.venv/bin/ruff check . --fix
```

### 后端编码约定

- **ORM 模型**：定义在 `database/models/` 中，每个文件包含 Base/Read/Create/Update schema 和 DAO 类。DAO 提供同步方法（`get_xxx`）和异步方法（`aget_xxx`）两套接口。
- **配置读取**：运行时可变配置从数据库读取（通过 `ConfigService.get_all_config()`），静态配置从 `config.yaml` 加载。
- **日志**：使用 Loguru，通过 `from loguru import logger` 导入。中间件自动注入 `trace_id` 用于链路追踪。
- **异步任务**：耗时操作投递到 Celery 队列。知识库任务路由到 `knowledge_celery` 队列，工作流任务路由到 `workflow_celery` 队列。

### 前端

- TypeScript 严格模式
- 组件使用函数式组件 + Hooks
- 状态管理优先使用 Zustand store，其次 React Context
- 国际化文本通过 `useTranslation()` 获取，支持中文、英文、日文

## 相关文档

- 系统架构总览 -- `docs/architecture/01-architecture-overview.md`
- 工作流引擎设计 -- `docs/architecture/02-workflow-engine.md`
- 知识库/RAG 流水线 -- `docs/architecture/03-knowledge-rag-pipeline.md`
- 数据模型定义 -- `docs/architecture/07-data-models.md`
- 部署与运维 -- `docs/architecture/08-deployment.md`
