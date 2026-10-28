# 审计问答列表：是否异常

验证毕昇平台「审计 → 应用使用」列表。门户运营后台的审计页嵌的是同一页。

## 要起的服务

- 毕昇后端，连 `config.yaml` 里的 171 MySQL
- 平台前端（或门户里打开审计）
- 数据库迁移已执行到 `f121_answer_abnormal_prep_failure`

## 数据

- 一个能打开审计列表的账号：超管，或角色里开了「审计」菜单
- 一条只有工具准备失败、执行中没有用到该工具的会话。当前库里两条问候（联网搜索未配置）属于这种
- 一条真正的失败会话：回答超时、工具已经调用并返回失败、工作流节点失败，或工作流整体失败
- 一条正常完成、没有失败说明的会话

表：`message_session.answer_abnormal`（0 否，1 是）、`chatmessage.extra` / `chatmessage.message` / `chatmessage.category`。无字段增删。`answer_abnormal` 的中文 COMMENT 为「任务是否异常: 0否 1是. 工具准备失败且执行中未使用不算」。

## 接口

`GET /api/v1/audit/session?answer_abnormal=1` 和 `answer_abnormal=0`。不传表示全部。

用户反馈筛选不再提供「复制」。反馈意见是列表里的意见按钮。

## 页面

1. 打开审计应用使用列表。
2. 用户反馈列第三个按钮悬停是「反馈意见」，筛选里没有「复制」。
3. 「是否异常」选「是」，搜索。真正失败的会话在列表里。只有联网搜索未配置、模型没有发起搜索的问候不在。
4. 打开那条问候的详情。列表是「否」，详情里仍能看到「联网搜索未配置」原句。
5. 打开真正失败的会话详情，能看到已记下的失败说明。再查一次 `answer_abnormal=1`，这条仍在。
6. 选「否」搜索，真正失败的会话不在，库里的 `answer_abnormal` 仍是 1。准备失败的问候在「否」里，库里是 0。

## 命令

本地实现时不跑。要跑时：

```bash
cd /Users/lkk/workplace/bisheng
BISHENG_E2E=1 \
BISHENG_BASE_URL=http://127.0.0.1:7860 \
BISHENG_TOKEN='登录后的 access_token' \
BISHENG_MYSQL_URL='mysql+pymysql://...' \
uv run --directory src/backend pytest ../../e2e/audit-answer-abnormal/test_answer_abnormal_flow.py -q
```

`src/backend` 的 pytest 默认只收集 `test/`，所以要写明这个文件路径。
