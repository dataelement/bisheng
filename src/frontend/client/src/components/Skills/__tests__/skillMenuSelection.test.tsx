import { fireEvent, render, screen } from '@testing-library/react';
import { DropdownMenu, DropdownMenuContent } from '~/components/ui';
import { SkillMenuPanel } from '../SkillMenuPanel';
import type { SkillRecord } from '../types';
import type { TaskModeSkill } from '~/store/linsight';

const personal: SkillRecord = {
  id: 7, name: 'pdf', displayName: '合同', description: '个人用的很长说明', source: 'personal',
  enabled: true, contentHash: 'abc', bundleMissing: false, updatedAt: '', preview: '', files: [],
};
const enterprise: SkillRecord = {
  id: 9, name: 'pdf', displayName: '合同', description: '企业用的很长说明', source: 'platform',
  enabled: true, contentHash: 'def', bundleMissing: false, updatedAt: '', preview: '', files: [],
};
const mockNavigate = jest.fn();
const mockRows = { current: [personal, enterprise] };

jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => ({
    com_skill_center_from_me: '来自我',
    com_skill_center_from_platform: '来自企业',
    com_skill_center_upload: '上传技能',
    com_skill_center_manage: '管理技能',
  }[key] ?? key),
}));
jest.mock('~/hooks/useIsClipped', () => ({ useIsClipped: () => [() => undefined, true] }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('bisheng-icons', () => {
  const icons = new Proxy({}, { get: () => () => null });
  return { Outlined: icons, Filled: icons, Colored: icons };
});
jest.mock('../useSkillCenter', () => ({
  useSkillCenter: () => ({
    personal: { data: mockRows.current.filter((skill) => skill.source === 'personal' && skill.enabled), isLoading: false, isError: false, refetch: jest.fn() },
    platform: { data: mockRows.current.filter((skill) => skill.source === 'platform' && skill.enabled), isLoading: false, isError: false, refetch: jest.fn() },
  }),
}));

function Menu({ selected = [] as TaskModeSkill[], onChange = jest.fn() }) {
  return (
    <DropdownMenu open>
      <DropdownMenuContent>
        <SkillMenuPanel selected={selected} onChange={onChange} onUpload={jest.fn()} />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

beforeEach(() => {
  mockNavigate.mockReset();
  mockRows.current = [personal, enterprise];
});

it('checks a row without closing the menu or opening the skill center', () => {
  const onChange = jest.fn();
  render(<Menu onChange={onChange} />);
  fireEvent.click(screen.getAllByRole('menuitem', { name: /合同/ })[0]);
  expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ id: expect.any(Number), name: 'pdf' })]);
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(screen.getAllByRole('menuitem', { name: /合同/ })).toHaveLength(2);
});

it('shows the personal and enterprise copies on separate rows', () => {
  render(<Menu />);
  const items = screen.getAllByRole('menuitem', { name: /合同/ });
  expect(items).toHaveLength(2);
  expect(screen.getByText(/来自我/)).toBeVisible();
  expect(screen.getByText(/来自企业/)).toBeVisible();
});

it('leaves only the enterprise row after the personal skill is turned off', () => {
  mockRows.current = [{ ...personal, enabled: false }, enterprise];
  render(<Menu />);
  expect(screen.getAllByRole('menuitem', { name: /合同/ })).toHaveLength(1);
  expect(screen.getByText(/来自企业/)).toBeVisible();
  expect(screen.queryByText(/来自我/)).not.toBeInTheDocument();
});

it('keeps the full text for a clipped row without opening details', () => {
  render(<Menu />);
  expect(screen.getByText(/个人用的很长说明/)).toBeInTheDocument();
  expect(mockNavigate).not.toHaveBeenCalled();
});
