import { renderToStaticMarkup } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom/server';
import { WorkbenchSidebar } from './WorkbenchSidebar';

let mockHomeTarget: string | null = '/c/new';
jest.mock('../useWorkbenchNavLinks', () => ({ useWorkbenchNavLinks: () => ({ links: mockHomeTarget ? [{ section: 'home', to: mockHomeTarget }] : [], showAdminEntry: false }) }));
jest.mock('./useSidebarEntries', () => ({ useSidebarEntries: () => [], splitSidebarEntries: () => ({ shown: [], more: [] }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: {} }) }));
jest.mock('~/components/Nav/NewChat', () => ({ useStartNewChat: () => jest.fn() }));
jest.mock('~/components/zhgyl/FlightReplay', () => ({ FlightReplay: () => null }));
jest.mock('~/components/zhgyl/scenes', () => ({ workspaceAsset: (path: string) => `/workspace/zhgyl/${path}`, advisorScene: () => '' }));
jest.mock('./SidebarConversationList', () => ({ SidebarConversationList: () => null }));
jest.mock('./SidebarProjects', () => ({ SidebarProjects: () => null }));
jest.mock('../UserPopMenu', () => ({ UserPopMenu: () => null }));
jest.mock('~/utils/platformAdminUrl', () => ({ getPlatformAdminPanelUrl: () => '/admin' }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('bisheng-icons', () => ({ Outlined: { MessagePlus: () => <svg /> } }));
jest.mock('@bisheng/ui', () => ({ Dropdown: () => null, DropdownItem: () => null, Tooltip: () => null }));

test.each([
  ['/c/synthetic-completed-chat', '/c/new'],
  ['/c/new?agent=orders&order=synthetic-one', '/c/new'],
  ['/c/new?module=procurement-forecast', '/c/new'],
  ['/menu-unavailable?plugin=home', '/menu-unavailable?plugin=home'],
])('brand leaves the remembered home destination %s for the permitted target %s', (remembered, expected) => {
  mockHomeTarget = remembered;
  const html = renderToStaticMarkup(<StaticRouter location="/c/synthetic-completed-chat"><WorkbenchSidebar /></StaticRouter>);
  const brand = html.match(/<a\b[^>]*class="[^"]*zh-sidebar-brand[^>]*>/)?.[0];
  expect(brand).toBeDefined();
  expect(brand).toContain(`href="${expected}"`);
  expect(brand).not.toContain('aria-current');
});

test('does not add a brand navigation link without a home entry', () => {
  mockHomeTarget = null;
  const html = renderToStaticMarkup(<StaticRouter location="/knowledge"><WorkbenchSidebar /></StaticRouter>);
  expect(html).not.toMatch(/<a\b[^>]*zh-sidebar-brand/);
});
