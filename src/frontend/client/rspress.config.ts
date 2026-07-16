import * as path from 'path';
import { defineConfig } from 'rspress/config';
import { pluginPreview } from '@rspress/plugin-preview';

/**
 * Component-library docs site (rspress).
 *
 * - Docs root is the gitignored `docs-ui-refactor/` at the repo root (design specs).
 * - Real ui components are imported via the `~` / `@` alias (mirrors vite.config).
 * - @rspress/plugin-preview renders live component demos inside markdown.
 * - i18n and custom theme intentionally NOT enabled yet.
 *
 * Run: `npm run dev:docs` (cwd: src/frontend/client).
 */
const clientSrc = path.join(__dirname, 'src');

export default defineConfig({
  // req 2: docs root = bisheng/docs-ui-refactor
  root: path.join(__dirname, '../../../docs-ui-refactor'),
  title: 'BiSheng 组件库',
  description: 'BiSheng client 设计规范 + 组件库',
  lang: 'zh', // single language — i18n intentionally not enabled (req 5)
  // Point straight at the app's stylesheet (tailwind directives + all design
  // tokens). A wrapper css with `@import` breaks rspack's cssExtractLoader.
  globalStyles: path.join(clientSrc, 'style.css'),

  // req 1: live component preview
  plugins: [pluginPreview({ previewMode: 'internal' })],

  themeConfig: {
    // req 6: two top-level sections — 文档 (specs) / 组件 (demos)
    // NOTE: the demos dir is ASCII (`components/`) on purpose — rspress v1's
    // client router fails to match nested routes with non-ASCII dir names.
    nav: [
      { text: '文档', link: '/00-总纲' },
      { text: '组件', link: '/components/button' },
    ],
    sidebar: {
      // 组件 section — component demos
      '/components/': [
        { text: '组件总览', link: '/components/index' },
        { text: 'Button 按钮', link: '/components/button' },
      ],
      // 文档 section — the existing design-spec markdown (kept flat, not moved)
      '/': [
        {
          text: '设计规范',
          items: [
            { text: '总纲', link: '/00-总纲' },
            { text: '字体 Typography', link: '/基础-字体规范' },
            { text: '色彩 Color', link: '/基础-色彩规范' },
            { text: '多端适配', link: '/基础-多端适配原则' },
            { text: '图标 Icon', link: '/基础-图标规范' },
            { text: '插画 Illustration', link: '/基础-插画规范' },
            { text: '滚动条', link: '/基础-滚动条规范' },
          ],
        },
        {
          text: '组件规范',
          items: [
            { text: 'Button 按钮', link: '/组件-Button按钮' },
            { text: 'Modal 弹窗', link: '/组件-Modal弹窗' },
          ],
        },
      ],
    },
  },

  builderConfig: {
    source: {
      define: {
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
        $fonts: path.join(__dirname, 'public/fonts'),
        // `import { URL } from 'url'` in api code must not resolve to the npm
        // `url` package (no URL named export) — shim with the browser global.
        url: path.join(__dirname, 'stubs/url-stub.ts'),
      },
    },
    tools: {
      cssLoader: {
        url: {
          // Leave root-relative (/workspace/...) and $fonts urls untouched —
          // they are app public paths; the docs site uses the system font stack.
          filter: (url: string) => !url.startsWith('/') && !url.startsWith('$fonts'),
        },
      },
      rspack: {
        resolve: {
          // Some ui components reach the `~/utils` barrel, which transitively
          // imports api modules using Node builtins. Demos never execute those
          // paths at runtime; stub them out so the browser bundle compiles.
          fallback: {
            crypto: false,
            url: false,
            fs: false,
            path: false,
            stream: false,
          },
        },
      },
    },
  },
});
