# 审计问答列表：是否异常

验证毕昇平台「审计 → 应用使用」列表。门户运营后台的审计页嵌的是同一页。

## 要起的服务

- 毕昇后端，连 `config.yaml` 里的 171 MySQL
- 平台前端（或门户里打开审计）
- 数据库迁移已执行到 `f120_message_session_answer_abnormal`

## 数据

- 一个能打开审计列表的账号：超管，或角色里开了「审计」菜单
- 一条日常问答会话：回答过程出现超时、工具失败或接口错误
- 一条正常完成的会话

表：`message_session.answer_abnormal`（0 否，1 是）、`chatmessage.extra` / `chatmessage.message` / `chatmessage.category`。本需求新增 `answer_abnormal` 列，中文 COMMENT 为「回答过程是否出现失败: 0否 1是」。没有别的字段改动。

## 接口

`GET /api/v1/audit/session?answer_abnormal=1` 和 `answer_abnormal=0`。不传表示全部。

用户反馈筛选不再提供「复制」。反馈意见是列表里的意见按钮。

## 页面

1. 打开审计应用使用列表。
2. 用户反馈列第三个按钮悬停是「反馈意见」，筛选里没有「复制」。
3. 「是否异常」选「是」，搜索。失败会话在列表里，正常会话不在。
4. 打开失败会话详情，能看到回答错误。再查一次 `answer_abnormal=1`，这条仍在。
5. 选「否」搜索，这条不在，库里的 `answer_abnormal` 仍是 1。

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
