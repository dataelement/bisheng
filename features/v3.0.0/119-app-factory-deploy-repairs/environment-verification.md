# F119：116 独立环境处置

日期：2026-11-03。授权来源：用户“按照建议修复下，116环境的特殊问题，单独在116环境上解决”。仅涉及 116；不以该授权更新其它环境。

## Node runtime 补齐：完成

- 目标节点：docker-116-vibe，linux/amd64。
- 现有已启用 profile：vibe-node20-release-20261025@1。
- 固定引用：`192.168.106.189:5443/vibe-release/bisheng-app-node@sha256:4eef7367dd0cec9209eec2e0c24ac4a68b29f8c19d480a923b86145cf2069f13`。
- Image ID：`sha256:9880455346cc5ad40ac3d0e285e6d1be9499775b9bf2d1d3e475ba078b247f9a`。

操作前重新读取 profile 并确认 digest、Image ID、UID/GID 与已核实目标一致。本地原先不存在该 Image ID；执行精确 digest 拉取后，核对本地 Image ID、RepoDigest、linux/amd64 和非 root 默认用户均符合原 profile，未修改 profile 或默认映射。

使用一次性无挂载容器验证 `node --version`：网络 none、只读根、UID/GID 10001、移除 capabilities、no-new-privileges、64 MiB、0.1 CPU、32 PIDs。输出 **v20.20.2**，正常退出并自动删除。

操作前后 backend、runtime-manager、app-proxy 的容器 ID、启动时间和运行状态一致；原 11 个 v2 应用容器集合一致。拉取策略仍为 **never**；未改数据库、出网、配置或权限，未更新服务镜像，未访问其它环境。

## 其它范围

此结果仅证明指定 Node runtime 已可用且可以执行，不代表 Node 应用发布、审批或主流程 E2E 已通过。

116 的 source-image 基础镜像、依赖材料供给与本功能代码部署分别记录；不能使用 Node 补齐结果将它们标为完成。该独立镜像处置阶段尚未开发正式修复；本轮本地代码已实现但未部署116，环境中仍可能出现此前核实的通用代码缺陷。
