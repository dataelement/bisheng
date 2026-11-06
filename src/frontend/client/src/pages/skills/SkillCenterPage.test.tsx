import { normalizeApiError } from '@bisheng/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { getSkillDetail, getSkillFile } from '~/api/skillCenter';
import { SkillCenterPage } from './SkillCenterPage';
import { type SkillRecord } from '~/components/Skills/types';

const personalSkill: SkillRecord = {
  id: 7, name: 'pdf', displayName: 'My contract', description: 'Personal description', source: 'personal',
  enabled: true, contentHash: 'abc', bundleMissing: false, updatedAt: '2026-01-02T00:00:00', preview: 'Steps', files: ['SKILL.md'],
};
const enterpriseSkill: SkillRecord = {
  id: 9, name: 'pdf', displayName: 'Enterprise contract', description: 'Enterprise description', source: 'platform',
  enabled: true, contentHash: 'def', bundleMissing: false, updatedAt: '2026-01-01T00:00:00', preview: '', files: [],
};
const missingSkill: SkillRecord = { ...personalSkill, id: 8, displayName: 'Missing bundle', bundleMissing: true, preview: '' };
const mutateAsync = jest.fn();
const mockShowToast = jest.fn();
const query = <T,>(data: T) => ({ data, isLoading: false, isFetching: false, isError: false, isSuccess: true, refetch: jest.fn() });
let mockCenter = {
  personal: query([personalSkill]),
  platform: query([enterpriseSkill]),
  personalCount: 1,
  enterpriseCount: 1,
  mutation: { isLoading: false, variables: undefined as { target?: SkillRecord } | undefined, mutate: jest.fn(), mutateAsync },
};

const copy: Record<string, string> = {
  com_skill_center_my_skills: 'My skills',
  com_skill_center_group_created: 'Created by me',
  com_skill_center_group_platform: 'From enterprise',
  com_skill_center_delete_failed: 'Delete failed, please retry',
  com_skill_center_bundle_missing: 'The skill bundle is missing. Please update it.',
  com_skill_center_open_failed: 'This skill cannot be opened right now.',
  com_skill_center_unavailable: 'This skill was deleted or disabled.',
  com_skill_center_update: 'Update skill',
  com_skill_center_cancel: 'Cancel',
  com_ui_delete: 'Delete',
  com_skill_center_more: 'More',
  com_skill_center_delete: 'Delete skill',
  com_skill_center_detail_source: 'Source',
  com_skill_center_detail_preview: 'Preview',
  com_skill_center_delete_title: 'Delete this skill?',
  com_skill_center_details: 'View details',
  com_skill_center_search: 'Search',
  com_skill_center_no_results: 'No results',
  com_skill_center_error_storage: 'Operation failed. Please retry.',
};

jest.mock('react-markdown', () => ({
  __esModule: true,
  default: ({ children }: { children?: string }) => children ?? null,
}));
jest.mock('remark-gfm', () => ({ __esModule: true, default: () => undefined }));
jest.mock('~/api/skillCenter', () => ({
  getSkillDetail: jest.fn(() => new Promise(() => undefined)),
  getSkillFile: jest.fn(() => new Promise(() => undefined)),
}));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string, vars?: { name?: string }) => {
    if (key === 'com_skill_center_delete_confirm') {
      return `Delete‘${vars?.name}’ prevents future tasks from using this skill. Existing conversations and generated results are kept.`;
    }
    return copy[key] ?? key;
  },
}));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('bisheng-icons', () => {
  const icons = new Proxy({}, { get: () => () => null });
  return { Outlined: icons, Filled: icons, Colored: icons };
});
jest.mock('~/components/Skills/useSkillCenter', () => ({ useSkillCenter: () => mockCenter }));
jest.mock('~/components/Skills/SkillUploadDialog', () => ({
  SkillUploadDialog: () => null,
}));
jest.mock('~/api/request', () => ({
  translateApiErrorMessage: (data: { status_code?: number }) => (
    data?.status_code === 11054 ? 'No permission for this skill. Contact an administrator.' : ''
  ),
}));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockShowToast }) }));

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});
beforeEach(() => {
  mutateAsync.mockReset();
  mockShowToast.mockReset();
  mockCenter = {
    personal: query([personalSkill]),
    platform: query([enterpriseSkill]),
    personalCount: 1,
    enterpriseCount: 1,
    mutation: { isLoading: false, variables: undefined, mutate: jest.fn(), mutateAsync },
  };
});

function openPage(path = '/skills') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}><SkillCenterPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

it('splits my skills into the two groups and counts each source', () => {
  openPage();
  expect(screen.queryByRole('tab', { name: /Skill square/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Skill square' })).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /Created by me/ })).toHaveTextContent('1');
  expect(screen.getByRole('heading', { name: /From enterprise/ })).toHaveTextContent('1');
  expect(screen.getByRole('button', { name: /My contract/ })).toBeVisible();
  expect(screen.getByRole('switch', { name: /My contract/ })).toBeVisible();
  expect(screen.getByRole('button', { name: /Enterprise contract/ })).toBeVisible();
  expect(screen.queryByRole('switch', { name: /Enterprise contract/ })).not.toBeInTheDocument();
});

it('searches within my skills', () => {
  openPage();
  const search = screen.getAllByRole('searchbox', { name: 'Search' })[0];
  fireEvent.change(search, { target: { value: 'My contract' } });
  expect(screen.getByRole('button', { name: /My contract/ })).toBeVisible();
  expect(screen.queryByRole('button', { name: /Enterprise contract/ })).not.toBeInTheDocument();
});

it('hides the enable switch on an enterprise skill', () => {
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /Enterprise contract/ }));
  expect(within(screen.getByRole('dialog')).queryByRole('switch')).not.toBeInTheDocument();
});

it('shows the chosen skill file', async () => {
  (getSkillDetail as jest.Mock).mockResolvedValueOnce({
    id: 9,
    preview: 'Enterprise skill instructions',
    files: ['SKILL.md', 'scripts/render_docx.py'],
    bundleMissing: false,
    contentHash: 'def',
  });
  (getSkillFile as jest.Mock).mockImplementation(async (_id: number, path: string) => (
    path === 'scripts/render_docx.py' ? 'print("ok")' : 'raw skill'
  ));
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /Enterprise contract/ }));
  const dialog = await screen.findByRole('dialog');
  expect(await within(dialog).findByText('Enterprise skill instructions')).toBeVisible();
  fireEvent.click(within(dialog).getByRole('button', { name: 'scripts/render_docx.py' }));
  expect(await within(dialog).findByText('print("ok")')).toBeVisible();
  fireEvent.click(within(dialog).getByRole('button', { name: 'SKILL.md' }));
  fireEvent.click(within(dialog).getByRole('button', { name: 'Source' }));
  expect(await within(dialog).findByText('raw skill')).toBeVisible();
});

it('keeps the skill list when a skill cannot be opened', async () => {
  (getSkillDetail as jest.Mock).mockRejectedValueOnce(new Error('missing'));
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /Enterprise contract/ }));
  const dialog = screen.getByRole('dialog');
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('This skill cannot be opened right now.');
  expect(screen.getByRole('button', { name: /My contract/, hidden: true })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Enterprise contract/, hidden: true })).toBeInTheDocument();
});

it('shows the enterprise skill body', async () => {
  (getSkillDetail as jest.Mock).mockResolvedValueOnce({
    id: 9,
    preview: 'Enterprise skill instructions',
    files: ['SKILL.md'],
    bundleMissing: false,
    contentHash: 'def',
  });
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /Enterprise contract/ }));
  const dialog = screen.getByRole('dialog');
  expect(await within(dialog).findByText('Enterprise skill instructions')).toBeVisible();
  expect(within(dialog).getAllByText('SKILL.md').length).toBeGreaterThan(0);
  expect(within(dialog).queryByRole('switch')).not.toBeInTheDocument();
});

it('keeps my skills when an old square link is opened', () => {
  openPage('/skills?view=square');
  expect(screen.queryByRole('tab', { name: /Skill square/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: 'Skill square' })).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /Created by me/ })).toBeVisible();
  expect(screen.getByRole('button', { name: /Enterprise contract/ })).toBeVisible();
});

it('keeps the card and explains a failed delete', async () => {
  mutateAsync.mockRejectedValue(new Error('no'));
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /My contract/ }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete skill' }));
  const confirm = screen.getByRole('dialog', { name: 'Delete this skill?' });
  expect(confirm).toHaveTextContent('Delete‘My contract’ prevents future tasks from using this skill. Existing conversations and generated results are kept.');
  expect(within(confirm).getByRole('button', { name: 'Cancel' })).toBeVisible();
  fireEvent.click(within(confirm).getByRole('button', { name: 'Delete' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Delete failed, please retry');
  expect(screen.getByRole('dialog', { name: 'Delete this skill?' })).toBeVisible();
  expect(screen.getByRole('button', { name: /My contract/, hidden: true })).toBeInTheDocument();
});

it('explains a missing bundle and offers an update', () => {
  mockCenter.personal = query([missingSkill]);
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /Missing bundle/ }));
  const details = within(screen.getByRole('dialog'));
  expect(details.getByText('The skill bundle is missing. Please update it.')).toBeVisible();
  expect(details.getByRole('button', { name: 'Update skill' })).toBeVisible();
});

it('returns to the list when the open skill is gone and leaves the others', async () => {
  openPage('/skills?skill=99');
  expect(await screen.findByRole('alert')).toHaveTextContent('This skill was deleted or disabled.');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /My contract/ })).toBeVisible();
  expect(screen.getByRole('button', { name: /Enterprise contract/ })).toBeVisible();
});

it('explains a failed switch with the server reason and keeps the previous state', () => {
  mockCenter.mutation.mutate = jest.fn((_change, options) => {
    options.onError(normalizeApiError({ status_code: 11054 }, { message: 'unavailable' }));
  });
  openPage();
  fireEvent.click(screen.getByRole('switch', { name: /My contract/ }));
  expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
    message: 'No permission for this skill. Contact an administrator.',
  }));
  expect(screen.getByRole('switch', { name: /My contract/ })).toBeChecked();
});

it('stays on the detail when the user turns off their own skill', () => {
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /My contract/ }));
  const details = within(screen.getByRole('dialog'));
  fireEvent.click(details.getByRole('switch'));
  expect(screen.getByRole('dialog')).toBeVisible();
  expect(details.getByRole('switch')).not.toBeChecked();
});
