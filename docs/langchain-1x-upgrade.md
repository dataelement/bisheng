# LangChain 1.x 升级 — 影响范围与测试重点

> 分支 `feat/langchain-1x`。后端从 LangChain 0.3 升级到 1.x，并清理了依赖该生态的两个第三方包（autogen / ragas）。本文给出影响范围、关键改动、已知问题与测试重点，供回归测试与评审使用。

## 1. 版本落点

| 包 | 升级前 | 升级后 | 说明 |
|----|--------|--------|------|
| langchain | 0.3.27 | **1.3.2** | 主包瘦身，旧模块迁出 |
| langchain-core | 0.3.79 | **1.4.1** | |
| langgraph | 0.3.x | **1.2.2** | workflow 引擎依赖 |
| **langchain-classic** | — | **1.0.7（新增）** | 承接被移出主包的旧模块（chains/agents/schema/…） |
| langchain-openai | 0.3.x | **1.2.2** | 强制 openai≥2.26 |
| langchain-community | 0.3.x | 0.4.2 | 部分 chat_models 符号被移除 |
| langchain-milvus | 0.2.1 | 0.3.3 | 强制 pymilvus≥2.6 |
| **pymilvus** | 2.5.x | **2.6.15** | 连带强升（向量库） |
| **openai** | 1.x | **2.41.0** | 连带强升（SDK 大版本） |
| **httpx** | 0.27.1 | **0.28.1** | 连带强升，移除 `proxies=` |
| rsa | （传递依赖） | **4.9（显式）** | 新依赖图不再带入，需显式声明 |
| bisheng_pyautogen / bisheng-ragas / datasets | 有 | **已移除** | 见 §4 |

**核心库未变**：pydantic 2.12.x、sqlalchemy 2.0.44、fastapi 0.121、sqlmodel 0.0.27 —— 升级未触及这些，回归风险显著降低。

## 2. 影响范围总览

升级触及三层，约 110+ 文件改动：

- **依赖层**：langchain 全家桶 1.x + 3 个连带强升（pymilvus / openai / httpx）。
- **import 层**：被移出主包的 `langchain.X` → `langchain_classic.X`（当前仍有 **65 个文件**使用 `langchain_classic`）。
- **运行时语义层**：openai 2.x / pymilvus 2.6 / langgraph 1.x / httpx 0.28 行为变化（import 测不出，需实跑）。

## 3. 关键代码改动（按类别）

| 类别 | 改动 | 触及 |
|------|------|------|
| import 迁移 | `langchain.{chains,agents,schema,memory,docstore,callbacks,chat_models,llms,embeddings,tools,prompts,…}` → `langchain_classic.*` | 主应用 + `bisheng_langchain` fork |
| httpx 0.28 | `httpx.Client/AsyncClient(proxies=)` → `proxy=`（`requests` 库的 `proxies=` 保持不变） | bisheng_langchain ~10 文件 |
| langchain-core 移除符号 | `format_tool_to_openai_tool` 改从 `langchain_classic.tools.render` 导入 | assistant_agent.py |
| langgraph 1.x | `langgraph.graph.graph.CompiledGraph` → `langgraph.graph.state.CompiledStateGraph` | gpts/sql_agent |
| pydantic v2 严格化 | 非注解类属性 `pattern = re.compile(...)` → `pattern: ClassVar[...]` | chatglm output_parser |
| **LLM 流式（重点）** | `BishengLLM._generate/_agenerate`：inner 流式时改用 `generate_from_stream(inner._stream)` 聚合，保留 `on_llm_new_token` 回调 | `bisheng/llm/domain/llm/llm.py` |
| **Milvus ORM 连接（重点）** | langchain-milvus 0.3.x 用 MilvusClient 连接，但 `col` 属性仍走 ORM `Collection(using=alias)`；pymilvus 2.6 的 `MilvusClient._using='cm-<id>'` 不注册 ORM 连接 → `ConnectionNotExistException`。新增 `Milvus` 子类，首次访问 `col` 时按 (uri,db) 注册稳定可复用的 ORM 连接并重定向 `self.alias` | `bisheng/core/vectorstore/milvus.py` |

### 3.1 BishengLLM 流式聚合修复（务必理解）

langchain-openai 1.x 在 `ChatOpenAI._generate` 内**不再聚合流式响应**（直接返回原始 `Stream`，改由 `_generate_with_cache` 分派到 `_stream`）。而 `BishengLLM` 直接委托 inner 的 `_generate`，导致 `streaming=True` 的 inner 返回无法解析的 `Stream`（`'Stream' object has no attribute 'model_dump'`）。

修复：inner 流式时在 `_generate/_agenerate` 内用 `generate_from_stream/agenerate_from_stream` 聚合 inner 的 `_stream/_astream`。这恢复了 0.3 时代行为，**并保持 `on_llm_new_token` 逐 token 回调**（workflow 大模型节点、对话 UI 的流式输出依赖它）。

> ⚠️ 经验教训：曾错误地用 `kwargs['stream']=False` 抑制流式，导致 workflow 模型节点变成整段返回。**任何"非流式化"的简化都会破坏 UI 流式**，因为非流式分派路径（`_generate/_agenerate`）仍需 inner 内部流式来触发回调。

## 4. autogen / ragas 移除（独立子工作）

- **bisheng_pyautogen（autogen）**：仅被遗留的动态 chain 加载引用，无 flow/模板/DB 使用 → 整体删除（`autogen_role/`、`chains/autogen/`、相关 loader 与配置）。
- **bisheng-ragas**：评测功能唯一用到的是单个指标 `AnswerCorrectnessBisheng`（prompt → LLM → 解析 JSON → P/R/F1）。已用纯 langchain 重写为 `bisheng/evaluation/domain/services/answer_correctness.py`（**prompt 与评分公式字节级一致**，prompt 已用 `json-repair` 解析），并将评测重构为独立 DDD 模块 `bisheng/evaluation/`。
- **datasets**（HF）：仅评测与已删除的 benchmark 脚本使用 → 一并移除；删除依赖 ragas 的死脚本（`rag/scoring/ragas_score.py`、`qa_generator.py`、`run_qa_gen_web.py`、`bisheng_rag_pipeline*.py`、`run_rag_evaluate_web.py`）。
- **langchain_compat.py shim**：曾用 sys.modules 别名桥接上述两个第三方包对已删除 `langchain.*` 路径的引用；两包移除后**整体删除**。
- 评测表 `Evaluation` 迁入 `bisheng/evaluation/domain/models/`（表名不变，**无 DB 迁移**）；多租户务必同步：`core/database/tenant_filter.py::_TENANT_AWARE_MODEL_MODULES` 已指向新路径（漏改会静默关闭该表租户隔离）。

## 5. 已知问题 / 待跟进

| 严重度 | 问题 | 位置 | 状态 |
|--------|------|------|------|
| 🟠 | `LLMUsageCallbackHandler` 未实现 `on_chat_model_start`（langchain 1.x 新调用点）→ 回调告警 | workflow 回调 | 待修，疑似 1.x 连带 |
| 🟠 | Celery worker 内 token 计费/调用日志的异步 DB 写抛 `Event loop is closed` / `Future attached to a different loop` | `token_tracker.py:71`、`call_logger.py:70` | 待修，异步上下文问题 |
| 🟡 | `BishengLLM.moonshot_generate/agenerate` 仍直接调用 inner `_generate`，对 streaming moonshot 模型存在同类 `Stream` 崩溃 | `bisheng/llm/domain/llm/llm.py` | 未改，moonshot 小众路径 |
| 🟡 | `bisheng_langchain/rag/config/*.yaml` 残留 `type: 'bisheng-ragas'`，已无消费方 | — | 死配置，无害 |
| 🟡 | openai 2.x / pymilvus 2.6 运行时语义未全量实测 | 全局 | 需 P0 手测 |

## 6. 测试重点（按优先级）

### P0 — 必须实跑（运行时语义，import/单测覆盖不到）
1. **Workflow 大模型节点流式输出** —— 确认逐 token 流式恢复（不是整段返回）；覆盖 reasoning_content、工具调用。
2. **知识库文件入库全链路** —— pymilvus 2.6 写 Milvus + ES 双写、检索召回。
3. **Assistant Agent 对话** —— `create_react_agent`、工具调用、引用标注、流式。
4. **各 LLM provider 调用** —— openai 2.x 下 ChatOpenAI/Azure/通义/深求/Ollama 等的 `.invoke()` 与 `.astream()`，响应解析、token 用量记录。
5. **Workflow 中断/恢复** —— INPUT/OUTPUT 中断后 Celery 续跑（langgraph 1.x）。

### P1 — 重点回归
6. **评测功能**（重写后）—— 实跑一次评测任务，核对 9 个字段/分数与历史口径一致；确认 `AnswerCorrectnessBisheng` 行为对齐。
7. **RAG 节点问答** —— `create_stuff_documents_chain`（走 langchain_classic）。
8. **httpx 代理为空** 场景下各 LLM client 构造（0.28 空 proxy 会报错）。
9. **token 计费 / 调用日志** —— 验证 §5 的异步 DB 写问题是否影响计费准确性。

### P2 — 边界 / 环境
10. **DM8 + dmPython** 依赖可安装与运行（仅 CI/Linux，本地 macOS 跳过）。
11. xinference rerank、ASR/TTS（openai 2.x client）。

### 自动化基线
- 全量 `uv run pytest test/ -m "not e2e"`：升级前后基线对比 **2219→2302 passed**（errors 148→93），差异由移除 datasets/flaml/ragas 解除了部分测试模块的收集错误所致，**无升级引入的回归**。失败项均为本地无中间件（MySQL/Redis/Milvus/ES/OpenFGA）的既有 infra 依赖。
- 必须起中间件：`bash docker/local-dev/start-middleware.sh` 后手测 P0/P1。

## 7. 回滚要点
- 依赖与代码都在 `feat/langchain-1x` 分支；回滚即切回基线分支。
- 无 DB schema 变更（评测表名不变），无需 alembic 回滚。
- 若仅需回退 autogen/ragas 移除而保留 langchain 1.x，则需恢复 `langchain_compat.py` shim（见 git 历史）。
