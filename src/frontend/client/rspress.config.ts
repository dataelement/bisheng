import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import { defineConfig } from 'rspress/config';
import { pluginPreview } from '@rspress/plugin-preview';
import tailwindcss from 'tailwindcss';
import autoprefixer from 'autoprefixer';

/**
 * Component-library docs site (rspress).
 *
 * - Docs root is `packages/ui/docs/` (design specs, git-tracked with @bisheng/ui).
 * - Real ui components are imported via the `~` / `@` alias (mirrors vite.config).
 * - @rspress/plugin-preview renders live component demos inside markdown.
 * - i18n and custom theme intentionally NOT enabled yet.
 *
 * Run: `npm run dev:docs` (cwd: src/frontend/client).
 */
const clientSrc = path.join(__dirname, 'src');

/**
 * Build stamp — the site is a static artifact (deploy-docs.sh rsyncs doc_build/ to
 * the dev server), so we need a way to tell how old a deploy is. Surfaced by the
 * component-index widget as a data attribute (devtools only, never page copy);
 * never assume a page on :3000 is live.
 */
const git = (cmd: string) => {
  try {
    return execSync(cmd, { cwd: __dirname, stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim();
  } catch {
    return 'unknown';
  }
};
const docsBuild = {
  time: new Date().toLocaleString('zh-CN', { hour12: false }),
  sha: git('git rev-parse --short HEAD'),
  branch: git('git rev-parse --abbrev-ref HEAD'),
};

/**
 * Which components @bisheng/ui publicly exports, read from its entry at build time.
 *
 * The 组件总览 「已迁库」 badge derives itself from this list: a demo page declares
 * WHICH component it documents (`component:` front matter) and the table decides
 * whether that component is in the library. Identity is stable, status is not —
 * so the badge can neither claim a migration the library does not back, nor go
 * missing because someone forgot to edit front matter after moving a component.
 *
 * Read at config load, so a component moving in/out of the library needs a dev
 * server restart to show up — same as the sidebar it sits next to.
 */
const uiComponents = (() => {
  try {
    const entry = fs.readFileSync(path.join(__dirname, '../packages/ui/src/index.ts'), 'utf8');
    // Both export forms point at the component dir: `from './components/Toast'`
    // and `from './components/Button/Button'`.
    const names = [...entry.matchAll(/from '\.\/components\/([A-Za-z0-9]+)/g)].map((m) => m[1]);
    return [...new Set(names)].sort();
  } catch {
    // Never break the docs build over a badge; the table just stops claiming
    // anything is migrated.
    return [];
  }
})();

export default defineConfig({
  // Docs live with the component library: src/frontend/packages/ui/docs
  // (git-tracked; the site stays hosted in client until the app-coupled demos
  // finish migrating onto @bisheng/ui).
  root: path.join(__dirname, '../packages/ui/docs'),
  // Build output next to the docs source (gitignored; CI artifact only).
  outDir: path.join(__dirname, '../packages/ui/doc_build'),
  title: 'BISHENG 组件库',
  description: 'BISHENG client 设计规范 + 组件库',
  lang: 'zh', // single language — i18n intentionally not enabled (req 5)
  // No SSG: demos import real app components, whose dependency tree reaches
  // browser/node-conditional packages (@dicebear/converter resolves its `node`
  // build under SSR and then needs the native `sharp` / `@resvg/resvg-js`,
  // which we don't install). `rspress dev` never hit this because it only
  // client-renders; `rspress build` prerenders and failed. Client-side
  // rendering is fine for an internal docs site, and it keeps every future
  // demo immune to the same class of SSR-only resolution breakage.
  ssg: false,
  // Point straight at the app's stylesheet (tailwind directives + all design
  // tokens). A wrapper css with `@import` breaks rspack's cssExtractLoader.
  globalStyles: path.join(clientSrc, 'style.css'),

  // req 1: live component preview
  plugins: [pluginPreview({ previewMode: 'internal' })],

  route: {
    // Working/meta docs that are not reader material — kept out of the site
    // entirely (routes AND search index): 00-总纲 (Claude-window charter) and
    // 元-文档撰写规范 (how-to-author-these-docs guide, for authors only).
    exclude: ['**/00-总纲.md', '**/元-文档撰写规范.md', '**/scripts/**'],
  },

  themeConfig: {
    // req 6: two top-level sections — 文档 (specs) / 组件 (demos)
    // NOTE: the demos dir is ASCII (`components/`) on purpose — rspress v1's
    // client router fails to match nested routes with non-ASCII dir names.
    nav: [
      // activeMatch drives the selected state: 组件 owns /components/*,
      // 文档 owns every other doc route (home included).
      // Each tab lands on its own section home, never on a particular page:
      // 文档 -> the site home (docs/index.md), 组件 -> 组件总览 (components/index.mdx).
      { text: '文档', link: '/', activeMatch: '^/(?!components/)' },
      { text: '组件', link: '/components/', activeMatch: '^/components/' },
    ],
    sidebar: {
      // 组件 section — component demos
      '/components/': [
        // antd-style categorized sidebar (mirrors the 文档 side): groups by kind.
        // Foundations (typography/color/icon/illustration) live together; real
        // components split by antd category.
        {
          text: '基础 Foundation',
          items: [
            { text: '字体 Typography', link: '/components/typography' },
            { text: '色彩 Color', link: '/components/color' },
            { text: '图标 Icon', link: '/components/icon' },
            { text: '插画 Illustration', link: '/components/illustration' },
          ],
        },
        {
          text: '通用 General',
          items: [
            { text: '按钮 Button', link: '/components/button' },
          ],
        },
        {
          text: '导航 Navigation',
          items: [
            { text: '面包屑 Breadcrumb', link: '/components/breadcrumb' },
          ],
        },
        {
          text: '数据录入 Data Entry',
          items: [
            { text: '输入框 Input', link: '/components/input' },
          ],
        },
        {
          text: '数据展示 Data Display',
          items: [
            { text: '文字提示 Tooltip', link: '/components/tooltip' },
            { text: '气泡卡片 Popover', link: '/components/popover' },
          ],
        },
        {
          text: '反馈 Feedback',
          items: [
            { text: '弹窗 Modal', link: '/components/modal' },
            { text: '二次确认 Confirm', link: '/components/confirm' },
            { text: '轻提示 Toast', link: '/components/toast' },
            { text: '状态页 State', link: '/components/state' },
            { text: '点赞点踩 Feedback', link: '/components/feedback' },
          ],
        },
      ],
      // 文档 section — the existing design-spec markdown (kept flat, not moved)
      '/': [
        {
          text: '设计模式',
          items: [
            { text: '文案 Copywriting', link: '/基础-文案规范' },
            { text: '多端适配 Responsive', link: '/基础-多端适配原则' },
            { text: '滚动条 Scrollbar', link: '/基础-滚动条规范' },
          ],
        },
        {
          text: '设计规范',
          items: [
            { text: '设计变量 Design Token', link: '/design-token' },
            { text: '字体 Typography', link: '/基础-字体规范' },
            { text: '色彩 Color', link: '/基础-色彩规范' },
            { text: '图标 Icon', link: '/基础-图标规范' },
            { text: '插画 Illustration', link: '/基础-插画规范' },
            { text: '圆角与阴影 Radius & Shadow', link: '/基础-圆角与阴影规范' },
          ],
        },
        {
          text: '组件规范',
          items: [
            { text: '按钮 Button', link: '/组件-Button按钮' },
            { text: '输入框 Input', link: '/组件-Input输入框' },
            { text: '复选框 Checkbox', link: '/组件-Checkbox复选框' },
            { text: '单选框 Radio', link: '/组件-Radio单选框' },
            { text: '开关 Switch', link: '/组件-Switch开关' },
            { text: '文字提示 Tooltip', link: '/组件-Tooltip文字提示' },
            { text: '气泡卡片 Popover', link: '/组件-Popover气泡卡片' },
            { text: '面包屑 Breadcrumb', link: '/组件-Breadcrumb面包屑' },
            { text: '弹窗 Modal', link: '/组件-Modal弹窗' },
            { text: '二次确认 Confirm', link: '/组件-Confirm二次确认' },
            { text: '抽屉 Drawer', link: '/组件-Drawer抽屉' },
            { text: '轻提示 Toast', link: '/组件-Toast轻提示' },
            { text: '状态页 State', link: '/组件-State状态页' },
          ],
        },
      ],
    },
  },

  builderConfig: {
    source: {
      // The app entry (src/main.jsx) imports this too — react-speech-recognition
      // (reached via the ~/hooks barrel) needs a global regeneratorRuntime.
      // rspress-overrides.css: docs-site-only fixes on top of the app css
      // (restores document flow so the sticky nav works — see file header).
      preEntry: [
        'regenerator-runtime/runtime',
        // globalStyles below loads the app's style.css, which no longer carries the
        // design tokens — they live in @bisheng/ui now. Load them here too, or every
        // color / type custom property on the docs site resolves to nothing.
        path.join(__dirname, '../packages/ui/src/styles/tokens.css'),
        path.join(__dirname, 'stubs/rspress-overrides.css'),
      ],
      define: {
        __DOCS_BUILD__: JSON.stringify(docsBuild),
        __UI_COMPONENTS__: JSON.stringify(uiComponents),
        // vite injects these globals (vite.config define); app code reached via
        // the `~/utils` barrel reads them at module scope — must exist here too.
        __APP_ENV__: JSON.stringify({ BASE_URL: '/workspace', BISHENG_HOST: '/admin' }),
        __VCONSOLE_ENABLED__: JSON.stringify(false),
        // vite exposes import.meta.env; rspack leaves it undefined. App code reads
        // DEV/BASE_URL/MODE/VITE_* at module scope, so give it a concrete object.
        'import.meta.env': JSON.stringify({
          DEV: true,
          PROD: false,
          MODE: 'development',
          BASE_URL: '/',
        }),
      },
    },
    resolve: {
      // mirror vite.config aliases so ui components resolve
      alias: {
        '~': clientSrc,
        '@': clientSrc,
        // Docs-site-only React widgets (not app code, not shipped in the app
        // bundle) — e.g. the generated component index on /components/.
        '@docs-site': path.join(__dirname, 'docs-site'),
        // Spec pages (packages/ui/docs/*.mdx) live outside this project, so a
        // bare `bisheng-icons` import resolves from the docs dir and misses the
        // package installed here. Alias it to the local install so spec mdx can
        // embed real icon components (plugin-preview fenced demos already
        // resolve it via the client context; this covers page-body imports).
        'bisheng-icons': path.join(__dirname, 'node_modules/bisheng-icons'),
        $fonts: path.join(__dirname, 'public/fonts'),
        // `import { URL } from 'url'` in api code must not resolve to the npm
        // `url` package (no URL named export) — shim with the browser global.
        url: path.join(__dirname, 'stubs/url-stub.ts'),
      },
    },
    tools: {
      // The docs build consumes design-token.js through a docs-only Tailwind
      // config (tailwind.docs.config.cjs) — proving the SSOT drives a real
      // Tailwind theme while the app's tailwind.config.cjs stays untouched.
      // Replacing the plugins array here supersedes the app's postcss.config.cjs
      // (which would otherwise resolve the app config), so Tailwind runs once.
      postcss: (config: any) => {
        config.postcssOptions = config.postcssOptions || {};
        config.postcssOptions.plugins = [
          tailwindcss(path.join(__dirname, 'tailwind.docs.config.cjs')),
          autoprefixer(),
        ];
      },
      cssLoader: {
        url: {
          // Leave root-relative (/workspace/...) and $fonts urls untouched —
          // they are app public paths; the docs site uses the system font stack.
          filter: (url: string) => !url.startsWith('/') && !url.startsWith('$fonts'),
        },
      },
      rspack: (config, { rspack }) => {
        // node:-scheme imports reached only on node-only paths (e.g.
        // @dicebear/core toFile → import('node:fs/promises') via the ~/hooks
        // barrel) — replace with an empty stub; rspack has no node: handling.
        config.plugins = config.plugins || [];
        config.plugins.push(
          new rspack.NormalModuleReplacementPlugin(
            /^node:fs\/promises$/,
            path.join(__dirname, 'stubs/empty-module.ts'),
          ),
        );
        config.resolve = config.resolve || {};
        // filenamify (ESM, imports node:path — an unbundlable scheme) comes
        // in via the ~/hooks barrel (usePresets); no demo executes it. The
        // alias must live at the raw-rspack layer — rsbuild's resolve.alias
        // did not take effect for this package.
        config.resolve.alias = {
          ...(config.resolve.alias as Record<string, unknown>),
          filenamify: path.join(__dirname, 'stubs/filenamify-stub.ts'),
        };
        // Some ui components reach the `~/utils` barrel, which transitively
        // imports api modules using Node builtins. Demos never execute those
        // paths at runtime; stub them out so the browser bundle compiles.
        config.resolve.fallback = {
          ...(config.resolve.fallback as Record<string, unknown>),
          crypto: false,
          url: false,
          fs: false,
          path: false,
          stream: false,
        };
        // Strip internal working sections (ledgers, change logs, scan
        // archives) from the spec md BEFORE the MDX compiler runs — a
        // remark-level strip misses the TOC/search, which rspress extracts
        // ahead of user remark plugins. Single source of truth stays the md.
        config.module = config.module || { rules: [] };
        config.module.rules = config.module.rules || [];
        config.module.rules.push({
          // .md only: rspress precompiles .mdx Node-side before webpack loaders
          // run, and MDX rejects the `<!-- site-hide -->` HTML comments this
          // loader relies on. Spec .mdx pages are authored reader-clean instead.
          test: /\.md$/,
          include: [path.join(__dirname, '../packages/ui/docs')],
          enforce: 'pre',
          use: [path.join(__dirname, 'plugins/strip-internal-loader.cjs')],
        });
      },
    },
  },
});
