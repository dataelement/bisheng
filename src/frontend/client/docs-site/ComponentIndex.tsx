/**
 * Component index table for /components/ — derived from the site, never hand-written.
 *
 * Everything in the table comes from rspress runtime `siteData`:
 *   - `siteData.pages`               -> the demo pages that actually exist (title, route, toc, frontmatter)
 *   - `siteData.themeConfig.sidebar` -> which group each page belongs to, and drift in both directions
 *
 * plus `__UI_COMPONENTS__` (rspress.config.ts) -> what @bisheng/ui actually exports,
 * which is what the 「已迁库」 badge reads. A page states WHICH component it documents
 * (`component:` front matter) and the library states whether that component is in it,
 * so nobody has to remember to flip a badge on migration day. Identities are stable;
 * statuses are what drift.
 *
 * So adding a demo page = create the mdx + a `status` front matter line + a sidebar
 * entry; the row grows by itself. Nothing here can go stale, because there is no
 * copy of the truth to forget to update. Drift that IS possible (page without a
 * sidebar entry, sidebar entry without a page, a `component:` the library does not
 * export) is rendered as a warning row instead of silently disappearing.
 */
import React from 'react';
import { usePageData } from 'rspress/runtime';

/** Build stamp injected by rspress.config.ts — surfaced as a data attribute, not as page copy. */
declare const __DOCS_BUILD__: { time: string; sha: string; branch: string };

/** What @bisheng/ui exports, injected by rspress.config.ts — drives the 已迁库 badge. */
declare const __UI_COMPONENTS__: string[];

const SECTION = '/components/';

interface SitePage {
  title: string;
  routePath: string;
  frontmatter?: Record<string, unknown>;
}

interface SidebarItem {
  text: string;
  link: string;
}

interface SidebarGroup {
  text: string;
  items?: SidebarItem[];
}

interface Row {
  title: string;
  route: string;
  group: string;
  status: string;
  /** True when the component this page documents is exported by @bisheng/ui. */
  migrated: boolean;
  note: string;
  /** Drift marker; empty when the page, the sidebar and the library agree. */
  warning: string;
}

const STATUS_LABEL: Record<string, string> = {
  done: '✅ 已落地',
  draft: '🟨 未定稿',
  todo: '⬜ 待补',
};

const cell: React.CSSProperties = { verticalAlign: 'top' };
const dim: React.CSSProperties = { color: 'var(--rp-c-text-2)' };

function normalizeRoute(route: string): string {
  const clean = route.split(/[?#]/)[0];
  return clean.length > 1 && clean.endsWith('/') ? clean.slice(0, -1) : clean;
}

export function ComponentIndex() {
  const { siteData } = usePageData();

  const pages = (siteData.pages as unknown as SitePage[]).filter((page) => {
    const route = normalizeRoute(page.routePath);
    return route.startsWith(SECTION) && route !== normalizeRoute(SECTION);
  });

  const sidebar = (siteData.themeConfig?.sidebar ?? {}) as Record<string, SidebarGroup[]>;
  const demoGroups = sidebar[SECTION] ?? [];

  const groupOf = new Map<string, string>();
  const sidebarOrder: string[] = [];
  demoGroups.forEach((group) => {
    (group.items ?? []).forEach((item) => {
      const route = normalizeRoute(item.link);
      groupOf.set(route, group.text);
      sidebarOrder.push(route);
    });
  });

  // Pages name the component they document; the library decides whether it is in.
  const inLibrary = new Set(typeof __UI_COMPONENTS__ === 'undefined' ? [] : __UI_COMPONENTS__);

  const rows: Row[] = pages.map((page) => {
    const route = normalizeRoute(page.routePath);
    const fm = page.frontmatter ?? {};
    const status = typeof fm.status === 'string' ? fm.status : '';
    const component = typeof fm.component === 'string' ? fm.component : '';
    const warnings = [
      groupOf.has(route) ? '' : '页面存在，但没挂进侧边栏',
      // Declared an identity the library does not back: the component was renamed,
      // dropped from src/index.ts, or the front matter has a typo.
      component && !inLibrary.has(component) ? `front matter 声明的 ${component} 不在 @bisheng/ui 的导出里` : '',
    ].filter(Boolean);
    return {
      title: page.title || route.replace(SECTION, ''),
      route,
      group: groupOf.get(route) ?? '',
      status: STATUS_LABEL[status] ?? (status || '⬜ 未标注'),
      migrated: component !== '' && inLibrary.has(component),
      note: typeof fm.statusNote === 'string' ? fm.statusNote : '',
      warning: warnings.join('；'),
    };
  });

  rows.sort((a, b) => {
    const ia = sidebarOrder.indexOf(a.route);
    const ib = sidebarOrder.indexOf(b.route);
    return (ia < 0 ? Number.MAX_SAFE_INTEGER : ia) - (ib < 0 ? Number.MAX_SAFE_INTEGER : ib);
  });

  const existing = new Set(rows.map((row) => row.route));

  // Sidebar entries whose page was renamed or never written.
  const brokenLinks = sidebarOrder.filter((route) => !existing.has(route));

  const stamp =
    typeof __DOCS_BUILD__ === 'undefined'
      ? undefined
      : `${__DOCS_BUILD__.time} · ${__DOCS_BUILD__.sha} (${__DOCS_BUILD__.branch})`;

  return (
    // The build stamp is deliberately not rendered — it lives on the wrapper as a
    // data attribute, so devtools can tell how old a static deploy is without the
    // page carrying a maintenance note for readers.
    <div data-docs-build={stamp}>
      <table>
        <thead>
          <tr>
            <th>组件</th>
            <th>分组</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.route}>
              <td style={cell}>
                <a href={row.route}>{row.title}</a>
                {row.warning && <div style={{ color: 'var(--rp-c-danger-1, #f53f3f)' }}>⚠ {row.warning}</div>}
              </td>
              <td style={{ ...cell, ...dim }}>{row.group || '—'}</td>
              <td style={cell}>
                {row.status}
                {row.migrated && <span style={dim}> · 已迁库</span>}
                {row.note && <span style={dim}> · {row.note}</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {brokenLinks.length > 0 && (
        <p style={{ color: 'var(--rp-c-danger-1, #f53f3f)' }}>
          ⚠ 侧边栏指向了不存在的页面：{brokenLinks.join('、')}
        </p>
      )}

    </div>
  );
}
