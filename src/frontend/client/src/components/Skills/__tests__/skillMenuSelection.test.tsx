import { fireEvent, render, screen } from '@testing-library/react';
import { DropdownMenu, DropdownMenuContent } from '~/components/ui';
import { SkillMenuPanel } from '../SkillMenuPanel';
import type { SkillRecord } from '../types';
import type { TaskModeSkill } from '~/store/linsight';

const personal: SkillRecord = {
  id: 7, name: 'pdf', displayName: 'Contract', description: 'A long personal description', source: 'personal',
  enabled: true, contentHash: 'abc', bundleMissing: false, updatedAt: '', preview: '', files: [],
};
const enterprise: SkillRecord = {
  id: 9, name: 'pdf', displayName: 'Contract', description: 'A long enterprise description', source: 'platform',
  enabled: true, contentHash: 'def', bundleMissing: false, updatedAt: '', preview: '', files: [],
};
const mockNavigate = jest.fn();
const mockRows = { current: [personal, enterprise] };

jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => ({
    com_skill_center_from_me: 'From me',
    com_skill_center_from_platform: 'From enterprise',
    com_skill_center_upload: 'Upload skill',
    com_skill_center_manage: 'Manage skills',
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
  fireEvent.click(screen.getAllByRole('menuitem', { name: /Contract/ })[0]);
  expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ id: expect.any(Number), name: 'pdf' })]);
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(screen.getAllByRole('menuitem', { name: /Contract/ })).toHaveLength(2);
});

it('shows the personal and enterprise copies on separate rows', () => {
  render(<Menu />);
  const items = screen.getAllByRole('menuitem', { name: /Contract/ });
  expect(items).toHaveLength(2);
  expect(screen.getByText(/From me/)).toBeVisible();
  expect(screen.getByText(/From enterprise/)).toBeVisible();
});

it('leaves only the enterprise row after the personal skill is turned off', () => {
  mockRows.current = [{ ...personal, enabled: false }, enterprise];
  render(<Menu />);
  expect(screen.getAllByRole('menuitem', { name: /Contract/ })).toHaveLength(1);
  expect(screen.getByText(/From enterprise/)).toBeVisible();
  expect(screen.queryByText(/From me/)).not.toBeInTheDocument();
});

it('keeps the full text for a clipped row without opening details', () => {
  render(<Menu />);
  expect(screen.getByText(/A long personal description/)).toBeInTheDocument();
  expect(mockNavigate).not.toHaveBeenCalled();
});
