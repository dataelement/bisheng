# 表单问卷 —— 托管应用示例

一个零第三方依赖的问卷应用：收集回答、落 SQLite、给出统计。它用来验证 BiSheng 应用工场的最小闭环 —— **本地写的应用 → `bisheng deploy` → 平台托管上线 → 所有人在应用广场里访问它**。

## 本地跑

```bash
python main.py          # 然后开 http://127.0.0.1:8080
```

没有依赖要装，没有 Dockerfile 要写。想验证平台上的路径行为，加一个环境变量即可：

```bash
BISHENG_APP_BASE_PATH=/apps/form-survey python main.py
# 页面里所有链接与 form action 都会带上前缀，跟平台上一致
```

## 部署到平台

```bash
bisheng login <平台地址> --api-key bs-sak-...
bisheng deploy .        # 读同目录的 bisheng-app.yaml
```

`deploy` 会依次做：密钥扫描 → 托管预检（构建 + 启动探活）→ 生成发布审批单。审批通过后应用上线，入口是 `<平台地址>/apps/form-survey`。

## 这个示例在演示什么

它同时是**托管运行契约**（PRD-1 DEV-04）的一份可执行说明。四条约定，缺一条都会在平台上出问题，而每一条在本地直接 `python main.py` 时都恰好是无害的默认值 —— 这是契约设计的目标：**同一份代码同一条路径，本地与平台的差别只在环境变量取值**。

| 约定 | 违反的后果 |
|---|---|
| 监听 `PORT` / `BISHENG_APP_PORT` | 硬编码端口 → 探活必失败 |
| 绑 `0.0.0.0` | 绑 `127.0.0.1` 在容器里只有进程自己连得上，健康探针一直失败**而日志干干净净** —— 最难查的一种「起来了但不健康」 |
| 外链带 `BISHENG_APP_BASE_PATH` | app-proxy 会剥掉前缀再转发，所以应用**收到**的是根路径；但应用**发出**的链接必须自己带前缀，漏一处那一处就跳到平台根路径去了 |
| 只往 `/data` 写 | 容器根文件系统只读，往别处写会在**运行期**才炸，而不是构建期 |

平台注入的相关变量：`PORT` · `BISHENG_APP_PORT` · `BISHENG_APP_BASE_PATH` · `BISHENG_APP_DB_PATH` · `BISHENG_APP_DB_URL` · `BISHENG_APP_HEALTH_PATH`。

## 目录

```
bisheng-app.yaml    应用清单（deploy 读的唯一配置文件）
main.py            应用本体，只用标准库
requirements.txt   故意留空
```

`requirements.txt` 空着是有意的：演示要验的是部署链路本身，不是依赖解析。空依赖意味着构建不需要能访问 PyPI —— 在 114 和信创基线上，「构建卡在 pip 拉不到包」是最常见、也最容易被误判成平台故障的失败。
