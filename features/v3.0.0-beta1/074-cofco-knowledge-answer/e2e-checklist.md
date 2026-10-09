# F074 调用与验收

新增接口：`POST /api/v2/filelib/answer`。使用后台生成的开放API Key，需已有 `knowledge:read` 能力；资源访问范围不因持有Key扩大。

## 调用

Key由环境变量注入，不写进文档、代码或日志；示例ID需替换为测试环境真实值。

```sh
curl --fail-with-body "$BISHENG_BASE_URL/api/v2/filelib/answer" \
  -H "Authorization: Bearer $BISHENG_OPEN_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"query":"报销需要哪些材料？","knowledge_base_ids":[8,9],"model_id":30,"top_k":10,"max_content":15000}'
```

返回统一JSON信封；`data`包含 `answer`、`has_context`、`model_id`、`references`。参考文件是实际送给模型的片段来源，不是整个目录，也不代表每个文件都在答案中实际引用。

`model_id`必须是当前租户工作台可用、已上线、无内置联网/工具的文本模型；不会自动换模型。可选 `filters.knowledge_base_filters` 按空间传入 `knowledge_base_id`、`tags`、`tag_match_mode="ANY"`。

无召回正文返回“未找到相关内容”，`has_context=false`且参考文件为空，不执行生成。参数非法沿用v2返回400；新错误10963/10964/10966对应502，超时10965对应504。供应商401不会被误报为调用方Key401。

## 发布

只需包含新接口的后端镜像，无新增表、迁移脚本、Worker或页面。需核对客户网关允许新路径，客户端/网关读取超时覆盖鉴权时间加120秒服务预算。旧召回、内部空间问答、助手和E+没有业务代码变更。

## 真实环境待验收

以下不能由本地mock替代；使用专用测试账号/空间和非敏感样本文档，不修改生产权限。

- [ ] AC-01/04/05：已知答案问题得到正确答案，参考文件确属提供的空间；无关问题不编造依据。
- [ ] AC-02/06：两空间都能取到资料，交换空间顺序不改变送入模型的来源选择规则。
- [ ] AC-03：授权但空的空间返回无结果；后台日志确认无生成调用。
- [ ] AC-07：标签只命中对应文件；无匹配不放宽范围。
- [ ] AC-08/09/10：缺Key、缺scope、越权/跨租户空间、错误资源类型被拒绝；合法S/D/PAT沿既有身份执行。
- [ ] AC-11/12：无权限文件、非主版本/未发布/已删除文件不进入模型；权限故障失败关闭。
- [ ] AC-13/14：模型离线、缺供应商、无效模型Key、超时返回错误，原文和密钥不泄露。
- [ ] AC-15/16：重复请求不创建会话或引用；旧 `/filelib/retrieve` 的输出和权限不变，原助手/E+正常。
- [ ] AC-17：可凭trace关联检索与生成耗时及终态，日志不含Key或新复制的正文。

## 可选环境自动测试

测试只读取预置空间并正常调用模型，不创建/删除资源；模型配额与审计会正常发生。

安全注入 `E2E_KNOWLEDGE_ANSWER_API_KEY`、`E2E_KNOWLEDGE_ANSWER_SPACE_ID`、`E2E_KNOWLEDGE_ANSWER_MODEL_ID`、`E2E_KNOWLEDGE_ANSWER_QUERY`；可选 `E2E_KNOWLEDGE_ANSWER_EMPTY_SPACE_ID`。`E2E_API_BASE`沿既有约定设为后端 `/api/v1` 地址。

```sh
cd src/backend
.venv/bin/python -m pytest test/e2e/test_e2e_knowledge_answer.py -q
```

未注入这些测试配置时4项skip，不表示环境验收通过。本地验证记录见 [tasks.md](./tasks.md)。
