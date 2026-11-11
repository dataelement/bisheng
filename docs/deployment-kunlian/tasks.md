# 部署文档任务（文档专用，不是特性实施授权）

范围：依据当前两仓库分支生成 Docker / Compose 部署说明及配套参考；不提交、推送、部署，不改变正式接口或历史特性状态。

- [x] D001：读取用户指定 telemetry 部署参考，核对当前分支 / commit / Drone 镜像命名。
- [x] D002：核对统一 Compose、安装器、后端入口、Gateway 配置和昆联双端校验规则。
- [x] D003：编写包含 Docker / Compose 安装、镜像获取、详细配置、启动、验收、备份与回退的手册。
- [x] D004：提供仅供复制审查的 Compose overlay、双端 YAML 与 Nginx 片段，不改现有部署文件。
- [x] D005：对新文档执行链接、空白、YAML / Compose 合并与参数覆盖检查；结果写入 verification.md。
- [x] D006：独立复核敏感信息与部署风险，修正退出窗口与Nginx预检顺序，交付文档包。
- [x] D007：按用户指定参考统一公网镜像源 cr.dataelem.com，更新四类镜像、环境变量、登录/拉取/inspect命令及故障说明；删除内网HTTP仓库配置流程。公网tag实际存在性继续NOT_RUN。

镜像仓库真实性、目标主机服务运行、真实SSO以及三项Workflow不变量均为部署人员后续受控验收，本次保持 NOT_RUN。
