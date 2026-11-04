# 应用入口跟随浏览器地址：热修审查

日期：2026-10-27。基线：`origin/feat/3.0.0`（本地核对提交 `c667d1bc09`）。适用 F054 AC-25、历史 T053 / T065 / T091 的发布页地址展示；用户要求采用教程页面的当前浏览器地址口径。后端返回字段、CLI、实际应用权限与运行路由不变。

## 根因与修改

原后端由 `app_runtime.entry_base_url` 加 `/apps/{slug}` 产生 `entry_url`，发布页原样展示/复制/打开/生成二维码。固定入口不同于用户实际访问的域名、协议或端口时，界面带回固定入口。历史注释把开发 Vite 未代理 `/apps` 当作不能使用当前 origin 的原因。

现四处共享 `window.location.origin + __APP_ENV__.BASE_URL + /apps/{encoded-slug}/`。保留空入口显隐规则；应用下线时链接仍展示，继续由入口授权/状态页判断可访问性。Vite 为 `/apps/` 增加 HTTP/WebSocket 代理，开发时由 `VITE_APP_PROXY_TARGET` 指定已部署入口；只提供 FastAPI 的 API 目标不能充当应用入口。配置说明及旧注释已同步。

## SDD 热修审查

| 维度 | 结论 | 依据 |
|---|---|---|
| 边界 | PASS | 空入口保持原规则；相对后端地址不影响页面展示；保留部署前缀和尾斜杠，slug编码 |
| 权限与认证 | PASS | 不新增接口或改授权；应用访问仍走既有nginx/app-proxy/backend身份判定 |
| 并发 | PASS | 地址为当前渲染的只读值，不引入缓存或共享状态 |
| 信息泄漏 | PASS | 四处不再展示配置中的固定主机地址；无新凭据、存储或日志 |
| 定向测试 | PASS | PublishTab 4例；实际Vite配置加载1例；未跑全量 |
| 风格 | PASS | 修改的TS/TSX通过ESLint；后端仅docstring修改，Ruff通过；架构守卫及diff check通过 |
| 文档 | PASS | F054设计现状、任务追加记录、开发代理README同步；后端固定地址合同不变 |

## 验证与交付边界

- `PublishTab.test.tsx`：4 passed，覆盖文字/复制/打开/二维码一致、下线态、部署前缀及相对入口、空入口。
- `config/vite.test.ts -t 'loads both real Vite configs'`：1 passed，实际加载Vite配置并验证独立应用入口及HTTP/WebSocket代理选项；其余10例未执行。
- 本地依赖复用现有virtual store；首次离线安装缺包及重复React环境问题已排除后，以上定向用例通过。没有修改锁文件或依赖清单。
- 未更新116前端镜像，未执行实际浏览器/手机扫码验收；截图的实例HTTP500不是本次修复对象。
- Overall：PASS（代码自审）；不等同于CI和部署验收通过。
