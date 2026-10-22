import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { getSkillDetail, getSkillFile } from '~/api/skillCenter';
import { SkillCenterPage } from './SkillCenterPage';
import { SkillRequestError, type SkillRecord } from '~/components/Skills/types';

const personalSkill: SkillRecord = {
  id: 7, name: 'pdf', displayName: '我的合同', description: '个人说明', source: 'personal',
  enabled: true, contentHash: 'abc', bundleMissing: false, updatedAt: '2026-01-02T00:00:00', preview: '步骤', files: ['SKILL.md'],
};
const enterpriseSkill: SkillRecord = {
  id: 9, name: 'pdf', displayName: '企业合同', description: '企业说明', source: 'platform',
  enabled: true, contentHash: 'def', bundleMissing: false, updatedAt: '2026-01-01T00:00:00', preview: '', files: [],
};
const missingSkill: SkillRecord = { ...personalSkill, id: 8, displayName: '缺文件', bundleMissing: true, preview: '' };
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
  com_skill_center_my_skills: '我的技能',
  com_skill_center_group_created: '我创建的',
  com_skill_center_group_platform: '企业提供',
  com_skill_center_delete_failed: '删除失败，请重试',
  com_skill_center_bundle_missing: '技能文件已丢失，请更新技能。',
  com_skill_center_open_failed: '这个技能暂时无法打开。',
  com_skill_center_unavailable: '该技能已删除或已停用。',
  com_skill_center_update: '更新技能',
  com_skill_center_cancel: '取消',
  com_ui_delete: '删除',
  com_skill_center_more: '更多',
  com_skill_center_delete: '删除技能',
  com_skill_center_detail_source: '源码',
  com_skill_center_detail_preview: '预览',
  com_skill_center_delete_title: '删除这个技能？',
  com_skill_center_details: '查看详情',
  com_skill_center_search: '搜索',
  com_skill_center_no_results: '没有结果',
  com_skill_center_error_storage: '操作失败，请重试。',
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
      return `删除‘${vars?.name}’后，后续任务将无法使用该 Skill，已有对话和生成结果保留。`;
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
    data?.status_code === 11054 ? '暂无该技能的操作权限，请联系管理员' : ''
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
  expect(screen.queryByRole('tab', { name: /技能广场/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: '技能广场' })).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /我创建的/ })).toHaveTextContent('1');
  expect(screen.getByRole('heading', { name: /企业提供/ })).toHaveTextContent('1');
  expect(screen.getByRole('button', { name: /我的合同/ })).toBeVisible();
  expect(screen.getByRole('switch', { name: /我的合同/ })).toBeVisible();
  expect(screen.getByRole('button', { name: /企业合同/ })).toBeVisible();
  expect(screen.queryByRole('switch', { name: /企业合同/ })).not.toBeInTheDocument();
});

it('searches within my skills', () => {
  openPage();
  const search = screen.getAllByRole('searchbox', { name: '搜索' })[0];
  fireEvent.change(search, { target: { value: '我的' } });
  expect(screen.getByRole('button', { name: /我的合同/ })).toBeVisible();
  expect(screen.queryByRole('button', { name: /企业合同/ })).not.toBeInTheDocument();
});

it('hides the enable switch on an enterprise skill', () => {
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /企业合同/ }));
  expect(within(screen.getByRole('dialog')).queryByRole('switch')).not.toBeInTheDocument();
});

it('shows the chosen skill file', async () => {
  (getSkillDetail as jest.Mock).mockResolvedValueOnce({
    id: 9,
    preview: '企业技能正文',
    files: ['SKILL.md', 'scripts/render_docx.py'],
    bundleMissing: false,
    contentHash: 'def',
  });
  (getSkillFile as jest.Mock).mockImplementation(async (_id: number, path: string) => (
    path === 'scripts/render_docx.py' ? 'print("ok")' : 'raw skill'
  ));
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /企业合同/ }));
  const dialog = await screen.findByRole('dialog');
  expect(await within(dialog).findByText('企业技能正文')).toBeVisible();
  fireEvent.click(within(dialog).getByRole('button', { name: 'scripts/render_docx.py' }));
  expect(await within(dialog).findByText('print("ok")')).toBeVisible();
  fireEvent.click(within(dialog).getByRole('button', { name: 'SKILL.md' }));
  fireEvent.click(within(dialog).getByRole('button', { name: '源码' }));
  expect(await within(dialog).findByText('raw skill')).toBeVisible();
});

it('keeps the skill list when a skill cannot be opened', async () => {
  (getSkillDetail as jest.Mock).mockRejectedValueOnce(new Error('missing'));
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /企业合同/ }));
  const dialog = screen.getByRole('dialog');
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('这个技能暂时无法打开。');
  expect(screen.getByRole('button', { name: /我的合同/, hidden: true })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /企业合同/, hidden: true })).toBeInTheDocument();
});

it('shows the enterprise skill body', async () => {
  (getSkillDetail as jest.Mock).mockResolvedValueOnce({
    id: 9,
    preview: '企业技能正文',
    files: ['SKILL.md'],
    bundleMissing: false,
    contentHash: 'def',
  });
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /企业合同/ }));
  const dialog = screen.getByRole('dialog');
  expect(await within(dialog).findByText('企业技能正文')).toBeVisible();
  expect(within(dialog).getAllByText('SKILL.md').length).toBeGreaterThan(0);
  expect(within(dialog).queryByRole('switch')).not.toBeInTheDocument();
});

it('keeps my skills when an old square link is opened', () => {
  openPage('/skills?view=square');
  expect(screen.queryByRole('tab', { name: /技能广场/ })).not.toBeInTheDocument();
  expect(screen.queryByRole('heading', { name: '技能广场' })).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: /我创建的/ })).toBeVisible();
  expect(screen.getByRole('button', { name: /企业合同/ })).toBeVisible();
});

it('keeps the card and explains a failed delete', async () => {
  mutateAsync.mockRejectedValue(new Error('no'));
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /我的合同/ }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '删除技能' }));
  const confirm = screen.getByRole('dialog', { name: '删除这个技能？' });
  expect(confirm).toHaveTextContent('删除‘我的合同’后，后续任务将无法使用该 Skill，已有对话和生成结果保留。');
  expect(within(confirm).getByRole('button', { name: '取消' })).toBeVisible();
  fireEvent.click(within(confirm).getByRole('button', { name: '删除' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('删除失败，请重试');
  expect(screen.getByRole('dialog', { name: '删除这个技能？' })).toBeVisible();
  expect(screen.getByRole('button', { name: /我的合同/, hidden: true })).toBeInTheDocument();
});

it('explains a missing bundle and offers an update', () => {
  mockCenter.personal = query([missingSkill]);
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /缺文件/ }));
  const details = within(screen.getByRole('dialog'));
  expect(details.getByText('技能文件已丢失，请更新技能。')).toBeVisible();
  expect(details.getByRole('button', { name: '更新技能' })).toBeVisible();
});

it('returns to the list when the open skill is gone and leaves the others', async () => {
  openPage('/skills?skill=99');
  expect(await screen.findByRole('alert')).toHaveTextContent('该技能已删除或已停用。');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /我的合同/ })).toBeVisible();
  expect(screen.getByRole('button', { name: /企业合同/ })).toBeVisible();
});

it('explains a failed switch with the server reason and keeps the previous state', () => {
  mockCenter.mutation.mutate = jest.fn((_change, options) => {
    options.onError(new SkillRequestError(11054));
  });
  openPage();
  fireEvent.click(screen.getByRole('switch', { name: /我的合同/ }));
  expect(mockShowToast).toHaveBeenCalledWith(expect.objectContaining({
    message: '暂无该技能的操作权限，请联系管理员',
  }));
  expect(screen.getByRole('switch', { name: /我的合同/ })).toBeChecked();
});

it('stays on the detail when the user turns off their own skill', () => {
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /我的合同/ }));
  const details = within(screen.getByRole('dialog'));
  fireEvent.click(details.getByRole('switch'));
  expect(screen.getByRole('dialog')).toBeVisible();
  expect(details.getByRole('switch')).not.toBeChecked();
});
