import { DesktopShellBridge } from './DesktopShellBridge';
let mockEntries = [{ id: 'knowledge', path: '/knowledge', to: '/knowledge', label: 'Knowledge', active: true, icon: null }];
const mockReport = jest.fn();
jest.mock('react', () => ({ useEffect: (effect: () => void) => effect() }));
jest.mock('react-router-dom', () => ({ useLocation: () => ({ pathname: '/knowledge', search: '' }) }));
jest.mock('~/components/Chat/desktopEmbedding', () => ({ isDesktopEmbedded: () => true }));
jest.mock('~/components/Chat/useDesktopNavigation', () => ({ useDesktopNavigation: () => {} }));
jest.mock('~/components/Chat/useDesktopAppearance', () => ({ useDesktopAppearance: () => {} }));
jest.mock('./useWorkbenchNavLinks', () => ({ useWorkbenchNavLinks: () => ({ links: [{ section: 'home', label: 'Welcome' }] }) }));
jest.mock('./WorkbenchSidebar/sidebarPrefs', () => ({ useSidebarPrefs: () => ({}) }));
jest.mock('./WorkbenchSidebar/useSidebarEntries', () => ({
  useSidebarEntries: () => mockEntries,
  splitSidebarEntries: (entries: unknown[]) => ({ shown: entries.slice(0, 3) }),
}));
afterEach(() => { delete window.dshChatPresentation; });
it('publishes only available entries and replaces them after grants change', () => {
  window.dshChatPresentation = { reportLanding: jest.fn(), reportNavigation: mockReport };
  DesktopShellBridge();
  expect(mockReport).toHaveBeenLastCalledWith({ homeLabel: 'Welcome', path: '/knowledge', entries: [{ id: 'knowledge', path: '/knowledge', label: 'Knowledge', active: true, primary: true }] });
  mockEntries = [];
  DesktopShellBridge();
  expect(mockReport).toHaveBeenLastCalledWith({ homeLabel: 'Welcome', path: '/knowledge', entries: [] });
});
