# 缓存 Token 明细修订 · 2026-09-10

用户已确认：缓存 Token 写入现有调用明细表，并通过模型转发接口返回客户端。本修订不增加界面或计费折算。

## 客户端变更（契约 0.5.0）

```json
{
  "prompt_tokens": 100,
  "completion_tokens": 20,
  "total_tokens": 120,
  "prompt_tokens_details": {
    "cached_tokens": 80,
    "cache_creation_tokens": null
  }
}
```

此对象位于 JSON 响应的 `usage`，或 `include_usage=true` 时 SSE 的最终 `usage` 块。`cached_tokens` 表示缓存命中读取；`cache_creation_tokens` 是 DSH 的缓存写入扩展字段。未测得为 null，上游明确为零才返回 0。总量与月度额度不重复累加缓存量。详情见 [client-api.md §7.3](./client-api.md#73-deepseek-扩展与-usage)。

客户端需接收 0.5.0 版本及新增字段，区分 null 与 0；不改变请求、鉴权、PKCE 或 SSE 时序。客户端实际接收确认与真实模型缓存命中联调仍待完成，本次未向外部团队发送消息。

## 部署顺序与 109 状态

按用户此前对未发布 DSH 功能的确认，不新增 Alembic revision：先在已有 `dsh_model_call` 表增加两列可空 BIGINT，再更新 API 和消费用量事件的 Worker。新建环境由 ORM 建表包含这两列。

| 列 | 类型 | 默认 / 历史数据 |
|---|---|---|
| cache_read_tokens | BIGINT NULL | NULL |
| cache_creation_tokens | BIGINT NULL | NULL |

109 独立 DSH 的 `dsh-backend` 所连接 MySQL `bisheng` 库已完成两列新增，并通过 schema inspect 验证类型与可空属性。只操作该独立实例；不回填历史记录，不部署服务、不重启容器。部署由用户处理。

API 与 Worker 需使用同一版代码；旧 Worker 的严格事件校验不能消费新增字段，不应混用。新代码接受缺失缓存字段的旧事件并按 NULL 落库。Gateway 无需更新。回退代码前先处理完含新字段的事件；新增列可保留，不需要删除明细或字段。

## 自动验证

90 项通过，1 项跳过（SQLite 不验证 MySQL 行锁并发）。验证范围：

- LangChain 统一缓存字段、OpenAI 原始明细、缓存读写原始字段和 DeepSeek 命中字段。
- 缺失、显式零、负值、布尔值、字符串、超出 BIGINT 范围的明细；异常缓存字段不丢弃可靠总量。
- HTTP JSON/SSE 返回；没有 include_usage 时不输出 usage 块，但仍写入结算事件。
- 独立真实 Redis（AOF + noeviction）Stream → SQLite 明细投影、重复事件幂等、同版本缓存值冲突拒绝，以及月汇总仅增加总 Token。
- 原有授权拒绝、模型协议、缺失用量、补记和投影 Worker 回归。

供应商响应由受控测试模型提供；未发起真实收费模型调用，未执行 DM 实机回归，也不代表桌面客户端已经适配。
