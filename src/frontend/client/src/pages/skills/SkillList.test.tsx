import { fireEvent, render, screen } from '@testing-library/react';
import { SkillList } from './SkillList';
import type { CenterSkill } from '~/components/Skills/types';
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/mock/demo/DemoTag', () => ({ DemoTag: () => null }));
jest.mock('@bisheng/ui', () => ({
  Switch: ({ checked, disabled, onCheckedChange, ...props }: { checked: boolean; disabled: boolean; onCheckedChange: (value: boolean) => void }) => <button role="switch" aria-checked={checked} disabled={disabled} onClick={() => onCheckedChange(!checked)} {...props} />,
  Tag: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));
test('personal and enterprise rows each expose an account availability switch', () => {
  const skills = [
    { id: 'platform:enterprise', name: 'enterprise', displayName: 'Enterprise', description: 'From company', source: 'platform', enabled: true },
    { id: 'personal:7', name: 'personal-7', displayName: 'Personal', description: 'Uploaded', source: 'personal', enabled: false, updatedAt: '2026-10-23' },
  ] as CenterSkill[];
  const onToggle = jest.fn();
  render(<SkillList skills={skills} sort="name" onSelect={() => {}} onToggle={onToggle} />);
  expect(screen.getByText('com_skill_center_group_created')).toBeInTheDocument();
  expect(screen.getByText('com_skill_center_group_platform')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('switch', { name: /Enterprise/ }));
  expect(onToggle).toHaveBeenLastCalledWith(skills[0], false);
  fireEvent.click(screen.getByRole('switch', { name: /Personal/ }));
  expect(onToggle).toHaveBeenLastCalledWith(skills[1], true);
});
