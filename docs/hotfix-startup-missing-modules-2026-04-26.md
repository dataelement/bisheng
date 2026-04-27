# 3002 登录异常热修记录

日期：2026-04-26 晚至 2026-04-27 凌晨

## 结论摘要

3002 登录异常不是前端构建问题。实际链路是：

`192.168.106.120:3002` → `192.168.106.115:8098 Gateway` → `192.168.106.116:7861` → `bisheng-test-backend`

Gateway 没有改配置，也没有重启。最终修复点在 `192.168.106.116` 的后端容器和业务库 schema。

## 主要问题

后端容器启动和登录路径连续暴露了几类缺口：

1. 容器内缺少 Python 模块：
   - `bisheng.department.domain.services.department_flow_service`
   - `bisheng.department.domain.services.department_archive_cleanup_service`
   - `bisheng.sso_sync.domain.services.wecom_gateway_absent_reconcile`
   - `bisheng.department.api.endpoints.department_limit`
2. 业务库缺少新代码已经引用的字段：
   - `department.concurrent_session_limit`
   - `user.disable_source`
3. 最开始误以为 3002 走的是 `192.168.106.109:7860`，后面通过 Gateway 日志确认 3002 实际走 `192.168.106.116:7861`。

## 服务器操作

### 1. 192.168.106.109 后端环境

这个环境做过排查和临时热修，但后来确认不是 3002 的实际 Gateway 上游。

操作内容：

- 复制热修 Python 文件到 `/tmp/`。
- `docker cp` 覆盖到：
  - `bisheng-backend:/app/bisheng/...`
  - `bisheng-backend-worker:/app/bisheng/...`
- 重启：
  - `bisheng-backend`
  - `bisheng-backend-worker`
- 给 `bisheng.department` 补过字段：

```sql
ALTER TABLE department
  ADD COLUMN concurrent_session_limit INT NOT NULL DEFAULT 0
  COMMENT 'Dept-wide max concurrent daily-mode chat users; 0=unlimited (F030)';
```

验证结果：

- `http://127.0.0.1:7860/api/v1/user/public_key` 返回 200。
- 后续确认 3002 不走这台机器，因此这不是最终链路修复点。

### 2. 192.168.106.115 Gateway

只读排查，没有改配置，没有重启。

确认内容：

- `bisheng-gateway` 正在监听 `8098->8080`。
- Gateway 日志显示它请求的上游是：

```text
192.168.106.116:7861
```

当 3002 返回 500 时，Gateway 日志里出现过：

```text
Connection refused: /192.168.106.116:7861
```

这说明 500 是 Gateway 上游后端不可用导致的，不应该盲改 Gateway 到 109。

### 3. 192.168.106.116 实际 3002 后端

这是最终热修目标。

容器：

- `bisheng-test-backend`
- `bisheng-test-backend-worker`

端口：

- 宿主机 `7861` 映射容器 `7860`

#### 覆盖的后端文件

通过 `scp` 先复制到 116 的 `/tmp/`，再用 `docker cp` 覆盖进后端和 worker 容器：

- `/app/bisheng/main.py`
- `/app/bisheng/department/api/endpoints/department_limit.py`
- `/app/bisheng/department/domain/services/department_flow_service.py`
- `/app/bisheng/department/domain/services/department_archive_cleanup_service.py`
- `/app/bisheng/sso_sync/domain/services/wecom_gateway_absent_reconcile.py`

说明：

- `main.py` 最终保留了 `/api/department-limit/*` 路由挂载。
- 中途曾尝试过删除流量控制入口来绕过启动缺模块，但最终没有采用该方案。
- `department_limit.py` 是最小可启动实现：部门总限流读写 `department.concurrent_session_limit`；资源级限流列表目前返回空分页，避免临时引入更大范围表结构。

#### 数据库 schema 热修

116 后端实际连接库为：

```text
192.168.106.116:3306/langflow
```

执行过的 schema 修复：

```sql
ALTER TABLE department
  ADD COLUMN concurrent_session_limit INT NOT NULL DEFAULT 0
  COMMENT 'Dept-wide max concurrent daily-mode chat users; 0=unlimited (F030)';
```

```sql
ALTER TABLE `user`
  ADD COLUMN disable_source VARCHAR(32) NULL
  COMMENT 'Set when delete=1 was forced by org sync/SSO; blocks non-super re-enable',
  ADD INDEX ix_user_disable_source (disable_source);
```

补充：

- `user.token_version` 已经存在，没有重复添加。
- `department.concurrent_session_limit` 补完后再次启动才暴露 `user.disable_source` 缺失。

#### 重启操作

每次覆盖文件或补字段后，重启：

```bash
docker restart bisheng-test-backend bisheng-test-backend-worker
```

## 验证结果

已验证：

- `192.168.106.116:7861/api/v1/user/public_key` 返回 200。
- `192.168.106.115:8098/api/v1/user/public_key` 返回 200。
- `192.168.106.120:3002/api/v1/user/public_key` 返回 200。
- `192.168.106.120:3002/api/v1/user/get_captcha` 返回 200。
- 对 `192.168.106.120:3002/api/v1/user/login` 发加密错误密码请求，返回业务错误：

```json
{"status_code":10600,"status_message":"Account or password error","data":null}
```

这个结果说明登录接口不再因为服务端异常返回 500，但当时没有拿到真实有效账号密码完成一次成功登录验证。

最新后端日志中，`/health` 返回 200，`/api/v1/user/login` 请求也已经进入正常业务返回路径。

## 本地代码状态

已提交并推送过：

- `24c13382b Restore daily chat startup by adding department flow limits`
  - 添加 `department_flow_service.py`
  - 添加对应单测

本次服务器热修对应的本地新增文件尚需正式提交：

- `src/backend/bisheng/department/api/endpoints/department_limit.py`
- `src/backend/bisheng/department/domain/services/department_archive_cleanup_service.py`
- `src/backend/bisheng/sso_sync/domain/services/wecom_gateway_absent_reconcile.py`
- `docs/hotfix-startup-missing-modules-2026-04-26.md`

当前工作区还有其他工具相关改动，不属于本次登录热修，提交时不要混进去。

## 后续必须处理

1. 把这次容器热修对应代码正式提交并走正常部署，否则镜像重建后容器内热修会丢。
2. 补正式数据库迁移，至少覆盖：
   - `department.concurrent_session_limit`
   - `user.disable_source`
3. 明确 `/api/department-limit/*` 的归属：
   - Gateway 当前有 `gt_department` / `gt_department_resource`。
   - bisheng 后端当前只做了最小部门总限流实现。
   - 资源级限流要么继续归 Gateway，要么补 bisheng 后端表和完整实现，不能长期保持两边语义不一致。
4. 116 是 3002 当前实际后端；109 上做过热修和字段补齐，但不是 3002 当前链路。后续环境说明需要更新，避免继续误判链路。

