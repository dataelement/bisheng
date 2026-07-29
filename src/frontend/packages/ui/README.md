# @bisheng/ui

BiSheng 前端共享组件库,同时服务 `client` 与 `platform` 两个应用。

## 铁律(permanent contract)

组件库是**纯展示层**。任何组件 **严禁** 引入:

1. **状态管理** — 不 import Recoil / Zustand / jotai;状态经 props/回调进出。
2. **请求层** — 不发 HTTP / SSE / WS;数据经 props 进,事件经回调出。
3. **i18n 业务 key** — 不调 `useTranslation`;所有文案通过 props 传入。
4. **路由** — 不 import react-router;跳转交给调用方回调。

违反任何一条的组件不属于这里,放回各自 app。

## 形态

- **源码直出**:`exports` 指向 TS 源码,由消费方(两个 app 各自的 Vite)编译。
  不预编译、不发 npm;workspace 内 `"@bisheng/ui": "workspace:*"` 直连,改动即时热更新。
- **token 双层契约**:`src/styles/tokens.css`(原始层 + 语义层 CSS 变量)+
  `tailwind-preset.cjs`(把语义 token 映射成 Tailwind 类)。组件只允许消费语义层
  (`text-text-1`、`bg-fill-2`、`bg-blue-500`、`btn-*`),禁止硬编码色值。
- 图标一律用 `bisheng-icons` npm 包,不在本包内新增图标组件。

## 开发

```bash
pnpm dev:ui         # 在 workspace 根运行 — 启动 rspress 文档站(菜单 + 实时示例),
                    # 即组件开发/预览环境;改本包源码即时热更新
pnpm typecheck      # 本包内运行 — 严格 TS 检查(strict: true)
```

文档源码在本包 `docs/`(git 跟踪);站点暂由 client 托管构建
(rspress 配置与依赖在 client,待 app 耦合的 demo 迁完后整体搬入本包)。
`doc_build/` 是构建产物,已 gitignore,正式发布由 CI 构建。

## 消费方接入

1. `"@bisheng/ui": "workspace:*"` 加入 dependencies。
2. tailwind config `content` 加入 `'../packages/ui/src/**/*.{ts,tsx}'`
   (否则组件里的 class 不会被生成)。
3. app 全局样式确保 token 变量可用:client 的 `style.css` 目前已内含同一份
   token(历史原因,保持同步);platform 接入时直接 `@import '@bisheng/ui/tokens.css'`。
