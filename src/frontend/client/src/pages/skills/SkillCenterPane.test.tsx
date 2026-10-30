import type { ReactNode } from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import i18n, { resources } from '~/locales/i18n';
import request from '~/api/request';
import { SkillCenterPane } from './SkillCenterPane';

jest.unmock('react-i18next');

jest.mock('~/api/request', () => ({ __esModule: true, default: { get: jest.fn(), put: jest.fn() } }));
jest.mock('~/components/Skills/skillPreviewStore', () => ({ listPersonalSkills: async () => [] }));
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ user: { id: '12' } }),
  useLocalize: () => jest.requireActual('react-i18next').useTranslation().t,
}));
jest.mock('~/utils', () => ({ cn: (...values: string[]) => values.filter(Boolean).join(' ') }));
jest.mock('~/mock/demo/DemoTag', () => ({ DemoTag: () => null }));
jest.mock('~/components/Skills/SkillUploadDialog', () => ({ SkillUploadDialog: () => null }));
jest.mock('~/components/ActionMenu', () => ({}));
jest.mock('~/components/ui/DropdownMenu', () => ({}));
jest.mock('@bisheng/ui', () => ({
  Button: ({ children, onClick }: { children: ReactNode; onClick: () => void }) => <button onClick={onClick}>{children}</button>,
  Switch: ({ checked, onCheckedChange, 'aria-label': label }: { checked: boolean; onCheckedChange: (value: boolean) => void; 'aria-label': string }) =>
    <button role="switch" aria-checked={checked} aria-label={label} onClick={() => onCheckedChange(!checked)} />,
  Tag: ({ children }: { children: ReactNode }) => <span>{children}</span>,
  StateView: ({ title }: { title: string }) => <p>{title}</p>,
}));
jest.mock('~/components/ui/Dialog', () => ({
  Dialog: ({ children, open }: { children: ReactNode; open: boolean }) => open ? <div role="dialog">{children}</div> : null,
  DialogContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: ReactNode }) => <p>{children}</p>,
}));

const keys = ['bisheng-docx', 'bisheng-pptx', 'bisheng-xlsx'] as const;
const records = keys.map((name, index) => ({ id: index + 1, name, builtin_key: name, source: 'platform', enabled: true,
  display_name: resources['zh-Hans'].translation.com_builtin_skills[name].name,
  description: resources['zh-Hans'].translation.com_builtin_skills[name].description }));
beforeEach(async () => {
  await i18n.changeLanguage('en');
  jest.mocked(request.get).mockImplementation(async url => url.endsWith('current-tenant')
    ? { status_code: 200, data: { leaf_tenant_id: 2 } }
    : { status_code: 200, data: records });
  jest.mocked(request.put).mockResolvedValue({ status_code: 200 });
});

function Page({ search = '', client }: { search?: string; client: QueryClient }) {
  return <QueryClientProvider client={client}><MemoryRouter>
    <SkillCenterPane search={search} uploadOpen={false} onUploadOpenChange={() => {}} />
  </MemoryRouter></QueryClientProvider>;
}

test.each(keys)('%s is translated through the API, hook, search, list and detail', async key => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } });
  const page = render(<Page client={client} />);
  const copy = resources.en.translation.com_builtin_skills[key];
  await screen.findByRole('button', { name: `${i18n.t('com_skill_center_details')}: ${copy.name}` });
  for (const search of [copy.name, copy.description, resources['zh-Hans'].translation.com_builtin_skills[key].name, key]) {
    page.rerender(<Page client={client} search={search} />);
    expect(screen.getByRole('button', { name: `${i18n.t('com_skill_center_details')}: ${copy.name}` })).toBeInTheDocument();
  }
  fireEvent.click(screen.getByRole('button', { name: `${i18n.t('com_skill_center_details')}: ${copy.name}` }));
  expect(within(screen.getByRole('dialog')).getByRole('heading', { name: copy.name })).toBeInTheDocument();
  expect(within(screen.getByRole('dialog')).getByText(copy.description)).toBeInTheDocument();
  page.unmount();
  client.clear();
});

test('the open detail follows language changes and the toggle uses the resource ID', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } });
  const page = render(<Page client={client} />);
  const key = 'bisheng-docx';
  const english = resources.en.translation.com_builtin_skills[key];
  fireEvent.click(await screen.findByRole('button', { name: `${i18n.t('com_skill_center_details')}: ${english.name}` }));
  await act(async () => { await i18n.changeLanguage('zh-Hans'); });
  const chinese = resources['zh-Hans'].translation.com_builtin_skills[key];
  expect(screen.getByRole('button', { name: `${i18n.t('com_skill_center_details')}: ${chinese.name}` })).toBeInTheDocument();
  const detail = within(screen.getByRole('dialog'));
  expect(detail.getByRole('heading', { name: chinese.name })).toBeInTheDocument();
  expect(detail.getByText(chinese.description)).toBeInTheDocument();
  await act(async () => { fireEvent.click(detail.getByRole('switch')); });
  expect(request.put).toHaveBeenCalledWith('/api/v1/dsh/skills/1/availability', { enabled: false });
  expect(client.getQueryData(['skill-center', JSON.stringify([2, '12']), 'catalog'])).toEqual(expect.arrayContaining([
    expect.objectContaining({ name: key, displayName: chinese.name, description: chinese.description }),
  ]));
  page.unmount();
  client.clear();
});
