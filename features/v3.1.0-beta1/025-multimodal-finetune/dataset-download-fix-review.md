# 数据集浏览器下载修复复核

基线：8960e9b165。范围：两个 Service 的三个浏览器下载签名入口，以及指定走查项目的 Nginx 配置；FT 直链、暂存上传、数据表和文件内容均不改变。

问题：接口使用 clear_host=False，前端替换域名后得到 /bucket/key，Nginx 将其回退到 SPA HTML。补 /object 后，未设置正确签名 Host 的 Nginx 又返回 SignatureDoesNotMatch。

修复：浏览器入口使用 clear_host=True，复用现有 MinIO 浏览器路径重写；签名查询串完整保留。部署 object location 的上游 Host 与实际 sharepoint 对齐，保留现有 bucket auth_request、查询串、Range 行为。

验证：新增三个回归用例在修复前全部失败（缺少 /object）；修复后 test/finetune、隔离 HTTP E2E 与 core 浏览器对象契约合计 329 项通过。Ruff、逐文件架构守卫与 diff 检查通过。真实环境验收须比较正常下载和 Range 字节及 SHA256，并核对非目标容器与数据库计数。

七维复核：边界、权限、并发、信息泄漏、测试、分层风格和文档同步无阻断问题。原归属/目录权限检查不变；未增加新查询或写入；后台 FT 传输的 clear_host=False 保留；没有新增硬编码凭据；设计已同步浏览器链接与代理签名契约。

结论：PASS。本地检查不代替实际部署验收；运行证据保存到目标环境本次 deploy-records 目录。
