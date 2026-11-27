import { renderToStaticMarkup } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom/server';
import { SidebarNavRow } from './SidebarNavRow';
import { sidebarChatEntry } from './sidebarChatEntry';

jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));

const entries = [
  { entryId: 'home', to: '/c/new', label: 'Home' },
  { entryId: 'zhgyl-forecast', to: '/c/new?module=procurement-forecast', label: 'Forecast' },
  { entryId: 'zhgyl-orders', to: '/c/new?module=order-tracking', label: 'Orders' },
];

test.each([
  ['/c/new', '', 'home'],
  ['/c/new', '?module=procurement-forecast', 'zhgyl-forecast'],
  ['/c/new', '?module=order-tracking&view=reminders', 'zhgyl-orders'],
  ['/c/new', '?agent=orders&order=synthetic-one', 'zhgyl-orders'],
  ['/c/synthetic-chat', '?agent=orders', 'zhgyl-orders'],
  ['/c/synthetic-chat', '?scene=orders', 'zhgyl-orders'],
  ['/c/synthetic-chat', '?agent=transport', 'home'],
  ['/c/synthetic-chat', '', 'home'],
  ['/c/new', '?agent=customs', 'home'],
  ['/linsight/synthetic-task', '', 'home'],
  ['/c/new', '?module=procurement-forecast&agent=orders', 'zhgyl-forecast'],
  ['/c/synthetic-chat', '?module=procurement-forecast', 'home'],
  ['/knowledge', '?module=order-tracking&agent=orders', null],
  ['/channel', '', null],
  ['/menu-unavailable', '?plugin=home', null],
  ['/c/new', '?module=unknown', null],
])('selects only the authoritative row on %s%s', (pathname, search, expected) => {
  const selected = sidebarChatEntry(pathname, search);
  expect(selected).toBe(expected);
    const html = renderToStaticMarkup(<StaticRouter location={pathname + search}>
      {entries.map(entry => <SidebarNavRow key={entry.entryId} {...entry} icon={<svg />} active={selected === entry.entryId} />)}
    </StaticRouter>);
    const anchors = html.match(/<a\b[^>]*>[\s\S]*?<\/a>/g) || [];
    expect(anchors).toHaveLength(3);
    const current = anchors.filter(anchor => anchor.includes('aria-current="page"'));
    const active = anchors.filter(anchor => /class="[^"]*\bactive\b/.test(anchor));
    expect(current).toHaveLength(expected ? 1 : 0);
    expect(active).toEqual(current);
    if (expected) expect(current[0]).toContain(entries.find(entry => entry.entryId === expected)!.label);
    anchors.filter(anchor => !current.includes(anchor)).forEach(anchor => {
      expect(anchor).not.toContain('bg-fill-2');
      expect(anchor).toContain('hover:bg-fill-1');
    });
});
