import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { SkillCenterPage } from './SkillCenterPage';
import type { PersonalSkill, PlatformSkill } from '~/components/Skills/types';

const personalSkill: PersonalSkill = {
  id: 'personal:report', name: 'my-report', displayName: 'My report', description: 'Personal reporting',
  source: 'personal', enabled: true, scope: 'tenant:user', revision: 'one', updatedAt: '2026-09-16T00:00:00Z',
  instructions: 'Write a report.', files: ['SKILL.md'], fileName: 'SKILL.md', size: 20, file: new Blob(),
};
const enterpriseSkill: PlatformSkill = {
  id: 'platform:report', name: 'company-report', displayName: 'Company report', description: 'Enterprise reporting',
  source: 'platform', enabled: true,
};
const mockMutation = { isLoading: false, mutateAsync: jest.fn() };
const query = <T,>(data: T) => ({ data, isLoading: false, isFetching: false, isError: false, refetch: jest.fn() });
let mockCenter = {
  identity: query('tenant:user'), personal: query([personalSkill]), platform: query([enterpriseSkill]), mutation: mockMutation,
};

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('bisheng-icons', () => {
  const icons = new Proxy({}, { get: () => () => null });
  return { Outlined: icons, Filled: icons, Colored: icons };
});
jest.mock('~/components/Skills/useSkillCenter', () => ({ useSkillCenter: () => mockCenter }));
jest.mock('~/components/Skills/SkillUploadDialog', () => ({
  SkillUploadDialog: ({ onSaved, onOpenChange }: { onSaved: () => void; onOpenChange: (open: boolean) => void }) =>
    <button onClick={() => { onSaved(); onOpenChange(false); }}>finish upload</button>,
}));

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});
beforeEach(() => {
  mockCenter = {
    identity: query('tenant:user'), personal: query([personalSkill]), platform: query([enterpriseSkill]), mutation: mockMutation,
  };
});

function openPage(path = '/c/skills') {
  return render(<MemoryRouter initialEntries={[path]}><SkillCenterPage /></MemoryRouter>);
}
function switchToEnterprise() {
  fireEvent.mouseDown(screen.getByRole('tab', { name: /com_skill_center_enterprise_skills/ }), { button: 0 });
}

it('separates personal and enterprise skills and removes the page preview banner', () => {
  openPage();
  expect(screen.getByRole('button', { name: /My report/ })).toBeVisible();
  expect(screen.queryByRole('button', { name: /Company report/ })).not.toBeInTheDocument();
  expect(screen.queryByText('com_skill_center_preview')).not.toBeInTheDocument();
  expect(screen.queryByText('com_skill_center_preview_notice')).not.toBeInTheDocument();
  switchToEnterprise();
  expect(screen.getByRole('button', { name: /Company report/ })).toBeVisible();
  expect(screen.queryByRole('button', { name: /My report/ })).not.toBeInTheDocument();
});

it('shows enterprise details as read-only, including direct links from the skill menu', () => {
  openPage('/c/skills?skill=platform%3Areport');
  const details = within(screen.getByRole('dialog'));
  expect(details.getByText('com_skill_center_platform_note')).toBeVisible();
  expect(details.queryByRole('button', { name: 'com_skill_center_update' })).not.toBeInTheDocument();
  expect(details.queryByRole('button', { name: 'com_skill_center_delete' })).not.toBeInTheDocument();
  expect(details.queryByRole('switch')).not.toBeInTheDocument();
  fireEvent.click(details.getByRole('button', { name: 'com_skill_center_close' }));
  expect(screen.getByRole('tab', { name: /com_skill_center_enterprise_skills/ })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('button', { name: /Company report/ })).toBeVisible();
  expect(mockMutation.mutateAsync).not.toHaveBeenCalled();
});

it('keeps personal update, delete and enable controls available', () => {
  openPage();
  fireEvent.click(screen.getByRole('button', { name: /My report/ }));
  const details = within(screen.getByRole('dialog'));
  expect(details.getByRole('button', { name: 'com_skill_center_update' })).toBeVisible();
  expect(details.getByRole('button', { name: 'com_skill_center_delete' })).toBeVisible();
  expect(details.getByRole('switch')).toBeChecked();
});

it('searches the current category and clears its search when switching categories', () => {
  openPage();
  fireEvent.change(screen.getByRole('searchbox', { name: 'com_skill_center_search' }), { target: { value: 'company' } });
  expect(screen.getByText('com_skill_center_no_results')).toBeVisible();
  switchToEnterprise();
  expect(screen.getByRole('searchbox', { name: 'com_skill_center_search' })).toHaveValue('');
  expect(screen.getByRole('button', { name: /Company report/ })).toBeVisible();
});

it('returns to personal skills after uploading from the enterprise category', () => {
  openPage('/c/skills?category=platform');
  fireEvent.click(screen.getByRole('button', { name: 'com_skill_center_upload' }));
  fireEvent.click(screen.getByRole('button', { name: 'finish upload' }));
  expect(screen.getByRole('tab', { name: /com_skill_center_my_skills/ })).toHaveAttribute('aria-selected', 'true');
  expect(screen.getByRole('button', { name: /My report/ })).toBeVisible();
  expect(screen.getByRole('status')).toHaveTextContent('com_skill_center_saved');
});

it('uses an administrator assignment empty state for enterprise skills', () => {
  mockCenter.platform.data = [];
  openPage('/c/skills?category=platform');
  expect(screen.getByText('com_skill_center_enterprise_empty_hint')).toBeVisible();
  expect(screen.queryByText('com_skill_center_empty_hint')).not.toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: 'com_skill_center_upload' })).toHaveLength(1);
});

it('keeps personal skills usable when the enterprise request fails', () => {
  mockCenter.platform.isError = true;
  openPage();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: /My report/ })).toBeVisible();
  switchToEnterprise();
  expect(screen.getByRole('alert')).toHaveTextContent('com_skill_center_error_platform');
});
