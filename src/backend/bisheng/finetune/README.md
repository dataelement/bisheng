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

模型/微调任务及服务管理仍要求 `get_tenant_admin_user`。公共父路由不再统一加此依赖；每个模型端点保留自己的管理员依赖，数据集端点使用 `get_dataset_user`。QA 内容动作仍走 permission application。

代码入口：`api/dependencies.py`、`api/finetune.py`、`domain/services/finetune_file.py`、`domain/models/preset_train.py`。回归在 `test/finetune/`，实施与验收边界见[修复审查](../../../../docs/reviews/dataset-menu-permissions-20261119.md)。
