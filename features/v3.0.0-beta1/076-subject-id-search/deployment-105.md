# 105 升级部署记录（2026-10-15）

目标：`192.168.106.105`，Compose 项目 `bisheng-dm`，工作目录 `/opt/server/dm/bisheng-dm/docker`。从现有 909 达梦环境向前升级至本分支，保留数据；未初始化、重建或降级数据库。

## 镜像与启动

- 前端：`cr.dataelem.com/dataelement/bisheng-frontend@sha256:c303c2716cc6326e2a4b83c13e3c768ea780566d51036f1544fda20efabb5f18`。
- 后端原始镜像：`cr.dataelem.com/dataelement/bisheng-backend@sha256:0f5a3f895f593942f5a62edef2de937e6f358adea6cb231c6e7b7b102e35fa91`。
- 达梦实测发现布尔比较编译问题后，基于原始后端镜像只替换 `core/database/subject_search.py`，构建 `cofco105-local:1021-dm-search-fix-20261015`；镜像 ID `sha256:96c28cf5b0481e5b2ee73dac84f580b64b493da53604a46f2c66f08794d23fef`，该文件 SHA256 `31d8b67adcca39921a40f870d337661e9521f2ff0ba90c26fc636f1703c64810`。源码和回归同步入分支，后续正式镜像需包含此修正。此本地镜像尚未发布镜像仓库，不能在其他机器直接拉取。
- API、普通 Worker、OCR Worker、既有 robot-debug 均使用同一修正版。没有启用新的调试服务；原有调试部署保留。
- 继续使用原 `docker-compose.yml`、`robot-debug.override.yml`、`save-as.override.yml`，末尾新增 `upgrade-1021.override.yml`。重启本套应用时必须保留这个覆盖文件，例如：

```sh
docker compose -p bisheng-dm \
  -f docker-compose.yml -f robot-debug.override.yml \
  -f save-as.override.yml -f upgrade-1021.override.yml \
  up -d --no-deps backend backend_worker backend_worker_ocr robot-debug frontend
```

## 数据与备份

先停止应用写入，再导出业务 schema 全部 123 张表和权限 schema 全部 6 张表，含字典元数据；逐表核对导出行数，完整读取压缩文件并记录 SHA256。这是逻辑数据快照，不是达梦原生 dexp 包；恢复需按保存的结构和原迁移恢复，不盲目整库覆盖。

备份目录：`/opt/server/dm/bisheng-dm/backups/cofco-105-20261015-1021/`（root 私有）。

- `business-data.pickle.gz`：65,109,632 字节，SHA256 `6008020a7d7ee45525d37b60b959280a0cb52d52d3c6a4ec41a13db05b7dde0b`。
- `openfga-data.pickle.gz`：9,859,448 字节，SHA256 `369250a92a6b871604f1d326a8b63243139be3365fa49d786d87ce6c3314abc1`。
- 同目录保存原 Compose、配置、启动脚本、nginx、容器清单、行数摘要、迁移/搜索日志和修正版镜像 Dockerfile。
- 原镜像保留标签 `cofco105-rollback:backend-before-1021-20261015`、`cofco105-rollback:frontend-before-1021-20261015`。

实际 revision 从 `f061_merge_cofco_909_f066_heads` 正向升级，补 F068 会话入口列、f062 合并 revision、情报游标列，最终为 `f076_subject_id_search_indexes`。两个 external_id 非唯一索引已建。迁移后全部原业务及权限表行数与停写快照一致，无缺失/新增表。

授权模型文件与升级前完全一致，不需要发布新授权模型；OpenFGA 和其他中间件未重建。业务 `config.yaml`、原挂载 `entrypoint.sh`、nginx 和数据挂载保留；配置及脚本与备份逐字节一致。

## 验证及边界

- API `/health` 返回 `{"status":"OK"}`；两端 `/`、`/workspace/` 返回 200。
- 实际达梦精确、前缀、大小写、非中段及字面通配符验证通过，用户和部门真实查询通过；修正后本地聚焦回归 153 passed、4 skipped。
- 后台节点与最终容器状态见服务器 `service-verification.log`。
- 未完成全入口浏览器交互验收、真实 API 专用夹具 E2E、并发 P95 与 MySQL 性能验收；没有把单次 SQL 冒烟当成性能验收。
- 已恢复应用写入后，不可直接用旧快照覆盖当前库。若需要回退，先停写并保存当前数据，评估新增数据和结构差异后再决定恢复方式。
