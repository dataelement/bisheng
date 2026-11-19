# 微调和数据集模块

## 数据集权限（2026-11-19）

数据集按当前有效 `dataset` 菜单准入，普通用户有该菜单即可查看、创建、下载、删除当前业务租户的数据集，包括同租户其他用户创建的数据集。菜单不是跨租户或问答库内容授权。身份与菜单沿用 `UserPayload`，不以角色编号或“模型管理员”替代；无菜单返回通用无权限，不返回模型共享只读错误。

全局超管及当前具体租户管理员保留与前端导航一致的固有数据集管理能力，不要求另行补普通角色菜单；普通用户必须通过有效菜单断言。该管理员身份通过已认证超管事实与 permission identity 协议核实，不采纳客户端标记。

| 入口 | 用途 | 权限与归属 |
| --- | --- | --- |
| `GET /api/v1/finetune/job/file/preset` | 列表、搜索、分页、total | 菜单 + DAO 严格当前租户 |
| `POST /api/v1/finetune/job/file/preset/upload` | 上传本地 JSON 的暂存阶段 | 菜单 + 租户/用户绑定的临时对象 |
| `POST /api/v1/finetune/job/file/preset` | 从暂存文件或问答库创建 | 暂存文件必须属于当前租户和本人；问答库必须全部属于当前租户且逐库通过 `visible` |
| `GET /api/v1/finetune/job/file/download` | 获取下载链接 | 数据集 URL 必须能匹配当前租户的数据库记录；个人微调暂存文件只接受当前租户/本人的新分区键 |
| `DELETE /api/v1/finetune/job/file/preset` | 删除数据集记录 | 菜单 + 严格当前租户查找 |

创建请求的 `name/files/qa_list` 与下载请求的 `file_url` 保持原字段。前端本地导入改用数据集专用暂存入口，返回仍为 `file_path`。旧的通用上传 URL、本地路径和任意外链不能作为创建来源，需要重新上传；旧数据库中已有数据集按当前租户记录证明归属，保持可读/可下载。无记录、无租户/用户分区证明的旧个人微调暂存键不再签名，需重新上传。

普通数据集对象存于 `finetune/dataset/{tenant}/{id}.json`；暂存上传存于临时桶 `finetune/dataset-upload/{tenant}/{user}/{id}.json`。个人微调上传使用独立 `finetune/train_file/personal/{tenant}/{user}/{id}.{ext}`，不能作为缺失/已删除数据集的下载兜底。以上路径是服务端生成的存储分区，不采纳客户端 tenant/user 参数。

模型管理、系统设置和 FT 服务管理要求 `get_tenant_admin_user`；微调任务使用 `get_finetune_user`，数据集管理使用 `get_dataset_user`。公共父路由不统一要求管理员。QA 内容动作仍走 permission application。

代码入口：`api/dependencies.py`、`api/finetune.py`、`domain/services/finetune_file.py`、`domain/models/preset_train.py`。回归在 `test/finetune/`，实施与验收边界见[修复审查](../../../../docs/reviews/dataset-menu-permissions-20261119.md)。


## 微调任务与模型管理权限（2026-11-19）

普通用户持有当前有效 `model` 菜单即可操作当前租户的微调任务，包括列表、详情、创建、停止、重命名、删除、发布和取消发布，也可上传本人训练文件、读取本租户训练数据选项和 GPU 信息。不按创建者限制任务；用户变更租户后，原租户的任务、服务、基础模型及个人上传文件不可继续查询或操作。超管及当前租户管理员保留固有任务能力。

FT 服务维护（`/api/v1/server/*`）仍仅超管或当前租户管理员可用。任务表单改用 `GET /api/v1/finetune/server/options`，只返回当前租户支持微调的服务 id/name，不返回服务端点或配置；基础模型选项只返回 id/model/sft_support。任务详情增加 `model_online`，普通用户查看已发布任务无需调用 FT 管理详情。

`GET /api/v1/finetune/training-data` 与 `/training-data/download` 是训练任务的数据读取入口，按 `model` 菜单授权；沿用列表 `list/total` 兼容格式。它们只允许读取当前租户的数据集和当前租户/本人的个人上传文件，不授予数据集创建、删除或问答库导出能力。数据集页面仍按 `dataset` 菜单独立管理。

创建任务先验证所有文件归属，再签名与启动远端任务。基础模型必须属于当前租户且关联所选服务；服务读取不再使用按 id 缓存的旧对象。任务、服务、基础模型及训练模型标记查询采用严格当前租户过滤；原生 UPDATE/DELETE 显式携带当前租户，不能借 Root 可见集合更新其他租户记录。

模型目录页面对普通模型菜单用户始终只读（单租户、多租户一致）。添加、编辑、删除、上下线、探测、系统模型设置仍由管理员接口校验。训练任务的发布/取消发布仅处理该任务产物，不授予通用 LLM 模型配置权限。

回归：`test/finetune/test_finetune_menu_api.py`（真实 HTTP 路由与 SQLite，外部训练/对象存储模拟），及前端 `ModelPage` 下权限测试。业务范围、基线失败与验收限制见 [本次修复记录](../../../../docs/reviews/finetune-model-menu-permissions-20261119.md)。
