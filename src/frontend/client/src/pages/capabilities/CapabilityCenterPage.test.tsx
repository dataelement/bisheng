import type { ReactNode } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import i18n, { resources } from '~/locales/i18n';
import { CapabilityCenterPage } from './CapabilityCenterPage';
import type { Capability } from '~/api/capabilities';

const companyKey = 'tianyancha_get_company_baseinfo';
const english = resources.en.tool.tools[companyKey];
const chinese = resources['zh-Hans'].tool.tools[companyKey];
const provider = Object.entries(resources.en.tool.categories).find(([, value]) => value.name === 'Tianyancha')?.[0] ?? '';
const mockCatalog: Capability[] = [{
  id: 'tool:42', resource_id: 42, kind: 'builtin', tool_key: companyKey,
  name: chinese.name, description: chinese.desc, provider, ready: true,
  availability_enabled: true, demo: false, trial: null, invocation_name: 'mcp__bisheng__bisheng_tool_42',
}];

jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: { id: 'test-user' } }),
  useLocalize: () => (key: string, options: object) => jest.requireActual('~/locales/i18n').default.t(key, options),
}));
jest.mock('@tanstack/react-query', () => ({
  useQuery: (key: string[]) => ({ data: key[1] === 'scope' ? 'test-scope' : mockCatalog }),
  useQueryClient: () => ({ invalidateQueries: jest.fn() }),
  useMutation: () => ({ reset: jest.fn(), mutate: jest.fn() }),
}));
jest.mock('~/api/capabilities', () => ({ getCapabilities: jest.fn(), setCapabilityAvailability: jest.fn(), runCapabilityTrial: jest.fn() }));
jest.mock('~/api/skillCenter', () => ({ getSkillScope: jest.fn() }));
jest.mock('~/components/Skills/useSkillCenter', () => ({ useSkillCenter: () => ({ platform: {}, personal: {} }) }));
jest.mock('~/pages/skills/SkillCenterPane', () => ({ SkillCenterPane: () => null }));
jest.mock('~/pages/skills/SkillList', () => ({ SkillListSkeleton: () => null }));
jest.mock('~/types/chat', () => ({ QueryKeys: { bishengConfig: 'config' } }));
jest.mock('bisheng-icons', () => ({ Outlined: { Skill: () => null, Plus: () => null } }));
jest.mock('lucide-react', () => ({ Wrench: () => null, CheckCircle2: () => null, Play: () => null }));
jest.mock('~/components/ModuleHome', () => ({
  MODULE_HOME_COLUMN: '', MODULE_HOME_FRAME: '',
  ModuleHomeHeader: ({ title, children }: { title: string; children: ReactNode }) => <header>{title}{children}</header>,
}));
// Keep the page and detail renderers real; layout primitives are lightweight test surfaces.
jest.mock('@bisheng/ui', () => ({
  Button: ({ children, onClick }: { children: ReactNode; onClick: () => void }) => <button onClick={onClick}>{children}</button>,
  SearchInput: ({ value, onChange, ...props }: { value: string; onChange: (event: unknown) => void; 'aria-label': string }) =>
    <input aria-label={props['aria-label']} value={value} onChange={onChange} />,
  StateView: ({ title }: { title: string }) => <p>{title}</p>,
  Switch: () => null, Input: () => null,
  Tabs: ({ items, onChange }: { items: { key: string; label: string }[]; onChange: (key: string) => void }) => <div>{items.map(item => <button key={item.key} onClick={() => onChange(item.key)}>{item.label}</button>)}</div>,
}));
jest.mock('~/components/ui/Dialog', () => ({
  Dialog: ({ children }: { children: ReactNode }) => <div role="dialog">{children}</div>,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
}));

function Page() {
  return <MemoryRouter initialEntries={['/?type=tool']}><CapabilityCenterPage /></MemoryRouter>;
}

beforeEach(async () => { await i18n.changeLanguage('en'); });

test('English search, list and selected details use the same existing tool translation', () => {
  render(<Page />);
  const search = screen.getByRole('textbox');
  for (const query of ['Company basic', 'legal rep.', 'Tianyancha', chinese.name]) {
    fireEvent.change(search, { target: { value: query } });
    expect(screen.getByRole('button', { name: english.name })).toBeInTheDocument();
  }
  fireEvent.click(screen.getByRole('button', { name: english.name }));
  const detail = within(screen.getByRole('dialog'));
  expect(detail.getByRole('heading', { name: english.name })).toBeInTheDocument();
  expect(detail.getByText(english.desc)).toBeInTheDocument();
  expect(detail.getByText(/Tianyancha/)).toBeInTheDocument();
});

test('an open detail and its list follow a language change together', async () => {
  const page = render(<Page />);
  fireEvent.click(screen.getByRole('button', { name: english.name }));
  await act(async () => { await i18n.changeLanguage('zh-Hans'); });
  page.rerender(<Page />);
  expect(screen.getByRole('button', { name: chinese.name })).toBeInTheDocument();
  expect(within(screen.getByRole('dialog')).getByRole('heading', { name: chinese.name })).toBeInTheDocument();
  expect(within(screen.getByRole('dialog')).getByText(chinese.desc)).toBeInTheDocument();
});

test('keeps the entered search when changing capability categories', () => {
  render(<Page />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Company basic' } });
  fireEvent.click(screen.getByRole('button', { name: i18n.t('com_capability_center.all') }));
  expect(screen.getByRole('textbox')).toHaveValue('Company basic');
  fireEvent.click(screen.getByRole('button', { name: i18n.t('com_capability_center.tool') }));
  expect(screen.getByRole('button', { name: english.name })).toBeInTheDocument();
  expect(screen.getByRole('textbox')).toHaveValue('Company basic');
});
