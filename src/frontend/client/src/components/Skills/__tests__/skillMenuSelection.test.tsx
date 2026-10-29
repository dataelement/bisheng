import { fireEvent, render, screen } from '@testing-library/react';
import { DropdownMenu, DropdownMenuContent } from '~/components/ui';
import { SkillMenuPanel } from '../SkillMenuPanel';
import type { SkillRecord } from '../types';
import type { TaskModeSkill } from '~/store/linsight';

const personal: SkillRecord = {
  id: 7, name: 'pdf', displayName: 'Fixture2151221516', description: 'Fixture2001020154299923034024456382713582826126', source: 'personal',
  enabled: true, contentHash: 'abc', bundleMissing: false, updatedAt: '', preview: '', files: [],
};
const enterprise: SkillRecord = {
  id: 9, name: 'pdf', displayName: 'Fixture2151221516', description: 'Fixture2022519994299923034024456382713582826126', source: 'platform',
  enabled: true, contentHash: 'def', bundleMissing: false, updatedAt: '', preview: '', files: [],
};
const mockNavigate = jest.fn();
const mockRows = { current: [personal, enterprise] };

jest.mock('react-router-dom', () => ({ useNavigate: () => mockNavigate }));
jest.mock('~/hooks', () => ({
  useLocalize: () => (key: string) => ({
    com_skill_center_from_me: 'Fixture264693325825105',
    com_skill_center_from_platform: 'Fixture26469332582022519994',
    com_skill_center_upload: 'Fixture19978202562521633021',
    com_skill_center_manage: 'Fixture31649297022521633021',
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
  fireEvent.click(screen.getAllByRole('menuitem', { name: /Fixture2151221516/ })[0]);
  expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ id: expect.any(Number), name: 'pdf' })]);
  expect(mockNavigate).not.toHaveBeenCalled();
  expect(screen.getAllByRole('menuitem', { name: /Fixture2151221516/ })).toHaveLength(2);
});

it('shows the personal and enterprise copies on separate rows', () => {
  render(<Menu />);
  const items = screen.getAllByRole('menuitem', { name: /Fixture2151221516/ });
  expect(items).toHaveLength(2);
  expect(screen.getByText(/Fixture264693325825105/)).toBeVisible();
  expect(screen.getByText(/Fixture26469332582022519994/)).toBeVisible();
});

it('leaves only the enterprise row after the personal skill is turned off', () => {
  mockRows.current = [{ ...personal, enabled: false }, enterprise];
  render(<Menu />);
  expect(screen.getAllByRole('menuitem', { name: /Fixture2151221516/ })).toHaveLength(1);
  expect(screen.getByText(/Fixture26469332582022519994/)).toBeVisible();
  expect(screen.queryByText(/Fixture264693325825105/)).not.toBeInTheDocument();
});

it('keeps the full text for a clipped row without opening details', () => {
  render(<Menu />);
  expect(screen.getByText(/Fixture2001020154299923034024456382713582826126/)).toBeInTheDocument();
  expect(mockNavigate).not.toHaveBeenCalled();
});
