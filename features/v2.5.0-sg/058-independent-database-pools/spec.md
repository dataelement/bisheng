# Feature: SQLAlchemy 同步与异步连接池独立配置

> **状态**：已确认（2026-07-20）  
> Spec Discovery 与规格确认均已完成：用户已确认配置结构、默认容量、兼容优先级、独立字段范围和配置样例修改边界。当前进入任务拆分阶段，`tasks.md` 确认前不创建功能分支、不修改生产代码。

- **优先级**：P1
- **所属版本**：v2.5.0-sg
- **Owner Feature**：F058-independent-database-pools
- **版本契约**：[v2.5.0 release contract](../../v2.5.0/release-contract.md)、[v2.5.0-sg release contract](../release-contract.md)

---

## 0. 范围界定

### IN

- 在现有 `database_pool` 下新增 `sync` 和 `async` 两个配置块。
- 同步、异步配置均独立支持：
  - `pool_size`
  - `max_overflow`
  - `pool_timeout`
  - `pool_recycle`
  - `pool_pre_ping`
- 新默认容量：同步 `pool_size=20`、`max_overflow=10`；异步 `pool_size=40`、`max_overflow=20`。
- 其余默认值保持一致：`pool_timeout=30`、`pool_recycle=3600`、`pool_pre_ping=true`。
- 兼容旧版 `database_pool` 扁平结构。
- 新旧配置混用时按“对应 Engine 默认值 → 旧扁平参数 → Engine 专属参数”逐层覆盖。
- 同步 SQLAlchemy Engine 只使用同步池最终参数；异步 Engine 只使用异步池最终参数。
- Alembic 继续通过同步 Engine 使用同步池配置。
- 将 `docker/bisheng/config/config.yaml` 中现有扁平样例迁移为嵌套结构。
- 保持 MySQL、DM8 和 SQLite 的现有方言兼容行为。

### OUT

- 不修改其他未显式声明 `database_pool` 的 YAML 文件。
- 不按 API、Celery、Linsight 或其他进程角色拆分连接池配置。
- 不增加连接池指标、运行时监控、告警或自动调优。
- 不支持连接池配置热更新；配置仍在进程启动时加载。
- 不移除或迁移现有同步数据库调用。
- 不新增依赖、HTTP API、数据库表、Alembic migration 或错误码。
- 不改变 Engine 懒创建、异步 Engine 按事件循环隔离和应用关闭时释放连接池的现有生命周期。

## 1. 概述与用户故事

### US-01：运维人员独立控制两类连接池容量

作为平台运维人员，我希望在同一配置文件中分别设置同步和异步 SQLAlchemy 连接池，以便根据两类数据库访问的实际并发差异控制连接数，避免同步池和异步池被迫使用相同容量。

### US-02：存量部署保持兼容

作为已有部署的维护人员，我希望旧版扁平 `database_pool` 配置继续有效，以便升级后无需立即迁移所有环境配置，也不会因配置结构变化导致启动失败或连接池参数丢失。

### US-03：开发人员获得明确的 Engine 配置边界

作为后端开发人员，我希望同步和异步 Engine 接收明确分离的参数，以便后续调整任一连接池时不会意外改变另一套连接池。

## 2. 配置契约

### 2.1 推荐的新配置结构

```yaml
database_pool:
  sync:
    pool_size: 20
    max_overflow: 10
    pool_timeout: 30
    pool_recycle: 3600
    pool_pre_ping: true
  async:
    pool_size: 40
    max_overflow: 20
    pool_timeout: 30
    pool_recycle: 3600
    pool_pre_ping: true
```

### 2.2 旧版兼容结构

旧版扁平参数继续同时作用于同步和异步配置：

```yaml
database_pool:
  pool_size: 30
  max_overflow: 12
  pool_timeout: 15
  pool_recycle: 1800
  pool_pre_ping: true
```

上述配置最终生成：

```text
sync:  pool_size=30, max_overflow=12, pool_timeout=15, pool_recycle=1800, pool_pre_ping=true
async: pool_size=30, max_overflow=12, pool_timeout=15, pool_recycle=1800, pool_pre_ping=true
```

### 2.3 混合配置与优先级

配置按以下顺序逐层覆盖：

```text
对应 Engine 默认值
→ database_pool 旧版扁平参数
→ database_pool.sync / database_pool.async 专属参数
```

示例：

```yaml
database_pool:
  pool_size: 30
  pool_timeout: 15
  sync:
    pool_size: 10
  async:
    max_overflow: 30
```

最终结果：

```text
sync:
  pool_size=10
  max_overflow=10
  pool_timeout=15
  pool_recycle=3600
  pool_pre_ping=true

async:
  pool_size=30
  max_overflow=30
  pool_timeout=15
  pool_recycle=3600
  pool_pre_ping=true
```

## 3. 验收标准

| ID | 角色 | 操作 | 预期结果 | 验证方式 |
|----|------|------|----------|----------|
| AC-01 | 运维人员 | 不配置 `database_pool` 启动应用 | 同步配置为 `20/10/30/3600/true`，异步配置为 `40/20/30/3600/true` | Pydantic 配置单元测试 |
| AC-02 | 存量部署 | 只提供旧版扁平配置 | 每个已提供的扁平参数同时覆盖同步和异步配置，未提供参数保留各自默认值 | 旧配置兼容单元测试 |
| AC-03 | 运维人员 | 只提供 `sync` 或只提供 `async` 配置 | 已提供配置覆盖对应 Engine；另一套 Engine 使用自身默认值 | 部分嵌套配置单元测试 |
| AC-04 | 运维人员 | 同时提供扁平参数和 `sync`/`async` 专属参数 | 先应用扁平参数，再由对应专属参数覆盖；两套最终结果符合 §2.3 | 混合优先级单元测试 |
| AC-05 | 运维人员 | 为同步和异步配置全部五项参数 | 两套配置分别保留各自的 `pool_size`、`max_overflow`、`pool_timeout`、`pool_recycle`、`pool_pre_ping` | 完整字段解析测试 |
| AC-06 | 系统 | 创建同步和异步 SQLAlchemy Engine | `create_engine()` 只收到同步最终参数，`create_async_engine()` 只收到异步最终参数 | Engine 构造参数与 pool 属性测试 |
| AC-07 | 运维人员 | 运行 Alembic online migration | Alembic 通过同步 Engine 建立连接，使用同步池配置，不读取异步池配置 | 管理器参数路由测试与代码路径检查 |
| AC-08 | 运维人员 | 使用迁移后的 Docker 配置启动 | 配置可被 `ConfigService` 解析，样例明确展示同步 `20+10` 与异步 `40+20` | YAML 解析验证 |
| AC-09 | 系统 | 使用 SQLite 创建同步和异步 Engine | 不支持的 QueuePool 容量参数继续被过滤，Engine 可正常创建和释放 | SQLite 同步/异步回归测试 |
| AC-10 | 系统 | 使用 MySQL 或 DM8 URL 创建 Engine | 保持驱动 URL 转换、MySQL `utf8mb4`、aiomysql pre-ping 修正和 DM8 URL 处理现有行为 | 现有专项测试与定向回归测试 |
| AC-11 | 存量部署 | 使用完整旧版扁平 `100+20` 配置升级 | 同步和异步两套 Engine 均继续使用 `100+20`，不被新默认容量覆盖 | 完整旧配置回归测试 |
| AC-12 | 系统 | 关闭应用或数据库上下文 | 已创建的同步和异步 Engine 继续按现有生命周期释放各自连接池 | 现有关闭行为测试/代码路径检查 |

## 4. 边界情况与失败语义

| ID | 场景 | 预期行为 |
|----|------|----------|
| E-01 | `database_pool` 缺失或为空对象 | 使用同步和异步各自默认值 |
| E-02 | 只配置旧版 `pool_size` | 两套 Engine 的 `pool_size` 都使用旧值；其他字段保留各自默认值 |
| E-03 | 只配置 `sync.pool_size` | 同步使用专属值；异步完整使用异步默认值 |
| E-04 | 扁平配置与专属配置包含同名字段 | 专属字段覆盖对应 Engine 的扁平字段 |
| E-05 | 专属配置只提供部分字段 | 未提供字段继承扁平值；扁平也未提供时继承对应 Engine 默认值 |
| E-06 | YAML 使用 `async` 键 | 配置模型通过字段别名正常解析，不要求用户使用 Python 内部字段名 |
| E-07 | SQLite 收到容量配置 | 同步 `StaticPool` 和异步 SQLite 路径继续移除不兼容参数，不因新结构报错 |
| E-08 | 配置字段类型不合法 | 沿用 Pydantic 配置校验失败语义，不增加静默回退 |

**明确不支持**：

- 旧扁平配置与新嵌套配置的运行时动态切换。
- 为不同事件循环设置不同的异步池参数。
- 为单个租户、请求或任务队列设置独立连接池。
- 通过数据库或 Redis 动态覆盖连接池配置。

## 5. 架构决策

| ID | 决策 | 结论 | 理由 |
|----|------|------|------|
| AD-01 | 外部配置结构 | 在 `database_pool` 下使用 `sync`、`async` | 保持配置聚合边界，避免新增两个无关顶层键 |
| AD-02 | 旧配置兼容 | 保留五个扁平字段并将其作为两套配置的公共覆盖层 | 现有部署可无修改升级，也支持渐进迁移 |
| AD-03 | 混合配置优先级 | Engine 默认值 → 扁平参数 → 专属参数 | 规则稳定、可组合，并允许只覆盖少数字段 |
| AD-04 | 默认容量 | 同步 `20+10`，异步 `40+20` | 对齐已确认的 API 同步使用面与异步主路径差异 |
| AD-05 | 参数独立范围 | 五项连接池参数全部独立 | 避免容量独立但超时、回收和健康检查仍隐式耦合 |
| AD-06 | 内部参数传递 | `DatabaseManager` 和 `DatabaseConnectionManager` 显式持有两套 Engine 参数 | 从类型和调用边界阻止同步/异步参数误用 |
| AD-07 | Alembic | 沿用同步 Engine 和同步池配置 | Alembic 当前只运行同步 online migration，无需引入异步迁移路径 |
| AD-08 | 配置样例范围 | 只迁移当前显式声明连接池的 Docker 样例 | 避免改动环境专用配置和扩大交付范围 |
| AD-09 | 生命周期 | 保持现有懒创建和清理逻辑 | 本功能只改变配置来源，不改变连接管理语义 |

## 6. 数据库、Domain 与 API

- 不新增或修改数据库表、ORM 模型和 Alembic migration。
- 不新增 Domain 实体、Repository、Service 或权限规则。
- 不新增或修改 HTTP API、请求响应模型和错误码。
- 本功能只调整启动配置模型与数据库基础设施参数传递。
- 不涉及多租户过滤、OpenFGA 或业务数据写入。

## 7. 配置与 Engine 链路

```text
config.yaml
  → ConfigService / Settings.database_pool
  → 同步与异步最终参数解析
  → ApplicationContextManager
  → DatabaseManager
  ├─→ DatabaseConnectionManager.engine
  │    → create_engine(sync kwargs)
  └─→ DatabaseConnectionManager.async_engine
       → create_async_engine(async kwargs)
```

约束：

- `DatabasePoolConf` 是新旧 YAML 兼容和优先级解析的唯一入口。
- Engine 创建层不得再次把同步、异步参数合并成一个共享字典。
- MySQL、DM8、SQLite 方言专属参数在各自 Engine 最终参数上继续应用。
- 异步 Engine 按事件循环创建时，每个实例都使用同一份异步最终配置。

## 8. 文件清单

### 新建

| 文件 | 说明 |
|------|------|
| `features/v2.5.0-sg/058-independent-database-pools/spec.md` | 本规格 |
| `features/v2.5.0-sg/058-independent-database-pools/tasks.md` | 规格确认后创建的任务清单 |

### 修改

| 文件 | 变更内容 |
|------|----------|
| `src/backend/bisheng/core/config/settings.py` | 定义同步/异步配置、默认值和旧扁平兼容解析 |
| `src/backend/bisheng/core/context/manager.py` | 向数据库上下文分别传递同步和异步参数 |
| `src/backend/bisheng/core/database/manager.py` | 保存并转发两套 Engine 配置 |
| `src/backend/bisheng/core/database/connection.py` | 同步、异步 Engine 分别合并和应用对应参数 |
| `src/backend/test/core/test_database_pool_config.py` | 覆盖默认值、兼容、优先级、参数路由和 SQLite 回归 |
| `docker/bisheng/config/config.yaml` | 将连接池样例迁移为 `sync`、`async` 嵌套结构 |

### 明确不修改

- `src/backend/bisheng/config.yaml`
- `src/backend/bisheng/config_3002.yaml`
- `src/backend/bisheng/config_3003.yaml`
- `docker/bisheng/config/config_dev.yaml`
- 任何数据库 migration、业务模块、前端文件和依赖锁文件

## 9. 非功能要求

- **兼容性**：旧扁平配置继续有效；MySQL、DM8、SQLite 现有行为保持。
- **可验证性**：每条配置合并规则和 Engine 参数路由均有自动化测试。
- **可维护性**：同步、异步参数在配置解析后保持显式分离，不依赖调用方约定区分。
- **性能**：配置解析只发生在启动阶段，不增加请求路径开销。
- **安全**：不记录或暴露 `database_url` 中的凭证，不改变密码解密逻辑。
- **回滚**：可通过恢复旧扁平配置和旧默认值回滚；不涉及数据回滚。

## 10. 风险

- 未声明 `database_pool` 的部署在升级后会采用更小的新默认池容量，数据库连接上限和高并发等待行为会发生变化。
- 已声明旧扁平配置的部署继续使用旧值；若运维误以为新默认已生效，可能造成容量认知偏差。
- `async` 是 Python 保留字，内部字段命名与 YAML alias 若处理错误会导致配置无法解析或导出字段不一致。
- 同步、异步参数在 Context/Manager/Connection 任一层被重新合并，都会破坏独立配置语义。
- macOS 不提供 DM8 驱动，真实 DM8 验证需在 Linux/CI 环境完成。

## 11. Spec Discovery 确认记录

| 日期 | 决策 | 用户确认 |
|------|------|----------|
| 2026-07-20 | 使用 `database_pool.sync` / `database_pool.async`，兼容旧扁平结构 | `1A` |
| 2026-07-20 | 默认同步 `20+10`，异步 `40+20` | `2B`（用户指定数值） |
| 2026-07-20 | 五项连接池参数全部独立 | `3A` |
| 2026-07-20 | 混合配置按默认值 → 扁平 → 专属逐层覆盖 | `1A` |
| 2026-07-20 | 只迁移当前显式声明连接池的 Docker 配置样例 | `2A` |
| 2026-07-20 | 归属版本为 v2.5.0-sg | 用户明确指定 |
| 2026-07-20 | 本规格内容与实施边界 | 用户明确“确认 spec” |

## 12. 暂停点

`tasks.md` 确认前：

- 不创建功能分支。
- 不修改生产代码、测试或 Docker 配置。

`tasks.md` 确认后，创建功能分支并按 Test-First 顺序实现；实现前仍需获得用户明确执行授权。

## 相关文档

- [v2.5.0 release contract](../../v2.5.0/release-contract.md)
- [v2.5.0-sg release contract](../release-contract.md)
- [Backend AGENTS.md](../../../src/backend/AGENTS.md)
- `src/backend/bisheng/core/database/connection.py`
- `src/backend/test/core/test_database_pool_config.py`
