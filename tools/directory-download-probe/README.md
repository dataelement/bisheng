# 企业微信目录下载能力验证（临时原型）

用途：验证企业微信实际容器能否让网页选择本地目录、创建目录、写入并读回文件。未修改知识空间正式下载逻辑，不访问业务数据，不需要账号或第三方服务。

## 部署和操作

页面文件位于 `src/frontend/client/public/static/directory-download-probe/`。知识空间文件列表上方有“目录下载验证（临时）”链接，电脑和手机共用；点击在当前窗口跳转，验证页提供返回按钮。正常构建前端镜像时随静态资源一起发布，部署后从页面点击即可，无需输入 URL。验证完成后应删除临时入口和验证资源。

1. 随前端镜像部署，默认地址为 `/workspace/static/directory-download-probe/index.html`；也可以将上述目录的 `index.html` 和 `probe.js` 原样部署至客户现有 HTTPS 站点的对应静态路径。使用 `/static/` 前缀避开开发服务器的 HTML 路由重写。必须能访问两个文件，不能被 SPA 回退改成应用 HTML。仅复制静态页不包含知识空间入口，入口需要部署本次前端改动。
2. 使用客户真实的企业微信入口和嵌套方式访问该路径。若业务在 iframe 中，测试页也应放入同样的 iframe；直接在外部浏览器打开成功不能代表内嵌成功。
3. 在 Windows、macOS（如涉及）、iOS、Android 的实际受支持客户端分别验证，记录系统和企业微信版本。
4. 点击“选择目录并验证写入”，授权一个测试保存位置。页面只在其中新建随机命名的 `bisheng-download-probe-*` 子目录。
5. 通过系统文件管理器检查 `说明.txt`、`子文件夹/sample.txt` 和 `空目录/` 实际存在。文本内容必须正常，页面结果须为 `write_read_passed`。
6. 复制结果框内容或截图反馈，并记录实际文件检查结果。测试结束后手动删除本次测试目录。

内网普通 HTTP 地址不是安全上下文；因 HTTP 缺少接口不等于该客户端在 HTTPS 下也不支持。HTTPS 的证书须被客户端信任。不能把浏览器私有存储（OPFS）当成用户可见下载目录。

## 结果边界

- `unsupported`：当前安全上下文未提供接口，该网页方案不可用。
- `insecure_context`：需修正访问环境后再测。
- `picker_aborted`：用户取消或浏览器中止，不作为不支持的证据。
- `failed`：保留具体阶段、异常名和消息；可能涉及嵌套来源限制、写入权限或容器实现。
- `write_read_passed`：两个合成测试文件写入、读回一致；还需人工确认系统可见目录。

这个原型只验证必要的本地目录写入能力。通过后，真实批量下载仍需验证认证、逐文件下载权限、目录结构和重名处理、大文件/多文件、失败重试及移动端切后台中断。原有接口只返回 ZIP 链接，不能直接作为多个原文件的下载清单。

电脑端通过不能推出手机端通过；检测到接口也不能替代实际写入。若任一必需平台不支持，就不能承诺企业微信所有端直接下载文件夹，需要保留 ZIP 或另议客户端方案。

参考：[MDN showDirectoryPicker](https://developer.mozilla.org/en-US/docs/Web/API/Window/showDirectoryPicker)、[Chrome File System Access](https://developer.chrome.com/docs/capabilities/web-apis/file-system-access)。
