# F089 浏览器样本验证

从仓库根目录运行，需 Node 20、已安装的工作区依赖及 macOS Google Chrome。不会连接业务后端或改动真实资料。

```sh
bash features/v3.0.0/089-shared-preview-citation/browser-smoke/regression.sh
node --experimental-websocket features/v3.0.0/089-shared-preview-citation/browser-smoke/run.mjs
# 先完成两端生产构建，再执行：
node --experimental-websocket features/v3.0.0/089-shared-preview-citation/browser-smoke/production.mjs
```

每次启动独立 Chrome 配置和本机临时端口，结束后关闭。结果、截图与缓存保留在输出的临时目录。开发样本临时生成两端入口，退出时删除；使用两端实际 Vite 配置、样式和别名，仅排除会重写测试入口的 HTML 路由插件。同时直接请求共享源码的 Vite 转换结果，避免依赖预优化缓存漏掉路径问题。真实业务权限、分享和保存操作仍需按上一层验收清单测试。

生产静态启动没有后端，client 环境接口的离线 404 属预期；脚本单独检查 ReferenceError/HighlightJS，报告保留全部异常供核对。资源体积和懒加载清单是静态文件检查，不等价于全部业务入口性能评测。
