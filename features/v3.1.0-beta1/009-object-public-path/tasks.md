# Tasks: 对象存储浏览器路径

**关联规格**: [spec.md](./spec.md)
**版本**: v3.1.0-beta1

---

## 状态

| 步骤 | 状态 | 备注 |
|------|------|------|
| spec.md | ✅ 已评审 | 2026-11-11 用户确认维持现稿 |
| design.md | ✅ 已评审 | 2026-11-11 用户确认；代码未改 |
| tasks.md | ✅ 已拆解 | 设计确认后拆解，实现未开始 |
| 实现 | ✅ 代码任务完成 | 8 / 8。页面 P0 因本机无监听端口保持待执行，原因写在 test-cases.md |

---

## 开发模式

按 Wave 顺序做。路径函数先有测试再实现。入口配置和开发代理放在签发与解析之后，避免只有新路径、没有放行判定。设计论证见 design.md，这里不重复。

手动页面验证对应 [test-cases.md](./test-cases.md)。中间件上的整站验证不作为本任务的本地门禁。

## Tasks

### Wave 1

- [x] **T001**: 浏览器路径函数的单元测试
  **文件**: `src/backend/test/core/test_browser_object_path.py`
  **逻辑**: 覆盖生成 `/object/{桶}/{键}`、旧形式与新形式解析、查询串保留、`/assets/` 下同名片段不改写、第一段不是当前两个桶时不改写
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-07
  **依赖**: 无

- [x] **T002**: 浏览器路径函数
  **文件**: `src/backend/bisheng/core/storage/browser_object_path.py`
  **逻辑**: 生成路径、改写文本、从两种形式解析桶和对象键。不访问数据库，不搬迁对象。论证见 design §3.3、§4.3
  **测试**: T001 通过
  **覆盖 AC**: AC-01, AC-05, AC-06, AC-07
  **依赖**: T001

### Wave 2

- [x] **T003**: 签发与桶名判定的测试
  **文件**: `src/backend/test/core/test_browser_object_issue.py`
  **逻辑**: 当前公共桶和临时桶可签出 `/object/` 地址；其它桶在交给浏览器时被拒绝；带公开主机名的完整地址不变；判定为允许、拒绝、空桶名
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-10, AC-11
  **依赖**: T002

- [x] **T004**: 签发拒绝与判定端点
  **文件**: `src/backend/bisheng/core/storage/minio/minio_storage.py`，存储 API 中新增不要求登录的判定端点并注册路由
  **逻辑**: `clear_host=True` 时非当前两个桶拒绝签发；剥主机后加 `/object`。`GET /api/v1/storage/browser-bucket` 读 `X-Object-Bucket`，允许 204，否则 403。不预分配错误码号，实现时占用对象存储段下一个未用号。论证见 design §3.2、§4.3
  **测试**: T003 通过
  **覆盖 AC**: AC-01, AC-03, AC-04, AC-10, AC-11
  **依赖**: T002, T003

### Wave 3

- [x] **T005**: 现有拼路径和解析改为共用函数
  **文件**: `knowledge/rag/pipeline/loader/base.py`，`knowledge/rag/pipeline/transformer/image_upload.py`，`api/services/etl4lm_loader.py`，`api/services/patch_130.py`，`workstation/api/endpoints/knowledge.py`，`core/storage/chat_attachment.py`，`knowledge/domain/services/temp_upload_service.py`，`workstation/domain/services/kb_image_stage.py`，`common/image_view/fetch.py`，`linsight/domain/services/workbench_impl.py`，以及把已存消息、附件和切片文本交给浏览器的读出点
  **逻辑**: 新拼出的切片图使用浏览器路径。解析接受两种形式。读出改写不写回数据库。论证见 design §4.1、§4.2
  **测试**: 扩展 T001 或为解析调用补针对性测试
  **覆盖 AC**: AC-05, AC-06, AC-08
  **依赖**: T002, T004

### Wave 4

- [x] **T006**: 三份站点入口
  **文件**: `docker/nginx/conf.d/default.conf`，`src/frontend/nginx.conf`，`docker/helm/bisheng/templates/configmap-nginx.yaml`
  **逻辑**: 增加 `/object/` 和 `/workspace/object/`。rewrite 去掉前缀后转发，查询串不变。转发前调用判定端点；子请求去掉登录头；判定 location 的 `proxy_pass` 不带 URI。删除按桶名匹配的 location。Host 复制该文件现有对象存储 location。论证见 design §3.1、§3.4、§5
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-11
  **依赖**: T004

- [x] **T007**: 本地开发代理与平台 Markdown
  **文件**: `src/frontend/client/vite.config.ts`，`src/frontend/platform/vite.config.mts`，`platform/src/pages/BuildPage/flow/FlowChat/MessageMarkDown.tsx`，`platform/src/pages/KnowledgePage/components/Markdown.tsx`
  **逻辑**: 开发代理只匹配固定前缀，转发前调用判定接口。Markdown 不再假设公共桶的字面量是 `bisheng`
  **覆盖 AC**: AC-03, AC-08, AC-09
  **手动验证**: 按 test-cases.md 的 TC-OBJ-001、TC-OBJ-008、TC-OBJ-009、TC-OBJ-012、TC-OBJ-013
  **依赖**: T004, T005

### Wave 5

- [x] **T008**: 对照测试用例做页面验证
  **文件**: 无新代码；记录在本任务下
  **逻辑**: 执行 test-cases.md 中能够在当前环境完成的 P0。做不到的条目保留「待执行」，并写明缺的样本或入口
  **覆盖 AC**: AC-01, AC-02, AC-03, AC-05, AC-08, AC-11
  **依赖**: T006, T007

---

## 实际偏差记录

- T008 本地 Docker 验收发现：判定子请求所在的 location 取不到入口 location 的正则捕获，桶名请求头为空，所有请求都被判为 403。改为在入口 location 用 `set $bs_object_bucket $2` 保存桶名，判定 location 改为前缀 `location /_object_bucket_ok/` 并读取该变量。三份入口配置已同步，接口契约不变。验证方式：本地 Docker Nginx 回归 TC-OBJ-001～006，并对两份配置运行 `nginx -t`。
