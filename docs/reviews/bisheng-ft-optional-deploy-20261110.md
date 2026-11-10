# bisheng-ft 可选部署恢复审查

日期：2026-11-10。目标分支：`feat/3.1.0-beta1`，排查基线 `99f81004fd`。
范围：部署回归修复；不修改微调 API、训练协议或数据库。

## 根因与修复

`85d968c6ac` 删除了 `docker/docker-compose-ft.yml` 和
`docker/bisheng-ft/config.yaml`，同时移除部署文档中的 FT 入口；
`finetune/domain/sft_backend.py`、`finetune/api/server.py` 及管理端
`ModelPage/components/RTConfig.tsx` 仍保留服务登记和微调调用。

恢复为主 Compose 文件的 `ft` profile，默认关闭。`install.sh --ft` /
`--no-ft` 维护持久化的 profile，保留 Gateway、app-runtime 和已有配置。
服务名、容器名、启动命令、健康检查、4 GiB 共享内存、全部 NVIDIA GPU
预留及两类模型数据挂载路径沿用删除前配置。Redis 通过同栈服务名访问，
等待 Redis 健康。旧版独立 Compose 文件入口由 `--profile ft` 替代。

FT 镜像与平台版本独立，默认
`cr.dataelem.com/dataelement/bisheng-ft:v0.5.0`；该 tag 通过只读
`docker manifest inspect --verbose` 验证可获取，平台为 `linux/amd64`。
旧 `.env` 缺少新变量也可解析；用户可覆盖镜像和宿主端口。

## 验证

- `bash scripts/tests/compose/test-install.sh`：18 项通过，新增 FT 启停配置、
  重跑保留、Gateway/app-runtime 组合、旧 `.env` 场景。
- 使用真实 Docker Compose 解析默认、FT、FT + Gateway + app-runtime：
  默认 13 个服务且不含 FT；FT 只新增 `ft_server`，基础服务配置逐项相同；
  GPU 预留、Redis 依赖、网络和挂载检查通过。
- 真实 Compose 解析缺少 FT 镜像变量的旧 `.env` 及自定义端口 `18000`：通过。
- 隔离临时目录与记录型 Docker 命令验证 `deploy.sh update ft` /
  `restart ft`：仅操作 `ft_server`，正确补充 `--profile ft`。
- 既有 `test/tool/test_work_knowledge_deploy.py` 运维入口回归：23 项通过
  （隔离运行，不加载应用 conftest）。
- Shell 语法、`git diff --check`、变更文件 arch-guard：通过。

## 七维审查

按 `sdd-code-review` 清单审查部署修复 diff。此次属于 hotfix track，
不新增 feature spec/design；现状与操作方法同步到 `docker/README.md`。

| 维度 | High | Medium | Low | 结果 |
| --- | --- | --- | --- | --- |
| 边界条件 | 0 | 0 | 0 | PASS |
| 权限与认证 | 0 | 0 | 0 | PASS |
| 并发安全 | 0 | 0 | 0 | PASS |
| 信息泄漏 | 0 | 0 | 0 | PASS |
| 测试覆盖 | 0 | 0 | 0 | PASS |
| 代码风格 | 0 | 0 | 0 | PASS |
| 文档同步 | 0 | 0 | 0 | PASS |

Overall：PASS（部署配置和脚本范围）。

本次未启动 FT 容器、未执行 GPU 训练验收。现场仍需准备支持的基座模型，
通过健康检查和模型/GPU 查询后完成一次真实训练；在“FT服务管理”登记
backend/worker 可达地址，同栈可用 `ft_server:8000`。
