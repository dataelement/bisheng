# 知识空间内容统计: 删除同步和贡献占比

验证数据集「知识空间内容统计」(`mid_knowledge_space_content_stat`) 的三件事:

1. 带文档入口的文件被 admin 删除后, 文件总数下降.
2. 当天新增的这份文件删除后, 新增文件数下降.
3. 按知识库大类看知识贡献占比, 各组相加等于 1.

## 要起的服务

- 毕昇后端, 连 `src/backend/bisheng/config.yaml` 里的 171 MySQL, 并已加载本次统计代码
- Redis, Elasticsearch. 本机没有 Celery worker 时, 测试在删除接口返回后, 直接跑一次内容统计投影函数

## 数据

- 身份: `user` 表 `user_id=1` 的 admin, 租户 1. 测试用本机配置里的 JWT 密钥签发短期 token, 不改密码
- 看板: 已发布的 `dashboard.id=10`
- 写入只发生在名称以 `e2e-content-stat-` 开头的知识库和文件. 结束时按本次插入的主键删除

表: `knowledge`, `knowledge_space_scope`, `knowledge_document`, `knowledge_document_version`, `knowledgefile`, `knowledge_recycle_item`. 无字段增删.

## 命令

```bash
cd /Users/lkk/workplace/bisheng/src/backend
PYTHONPATH=/Users/lkk/workplace/bisheng/src/backend \
config=config.yaml BISHENG_E2E=1 BISHENG_BASE_URL=http://127.0.0.1:7860 \
  .venv/bin/pytest ../../e2e/knowledge-space-content-stat/test_content_stat_flow.py -q --tb=short
```
