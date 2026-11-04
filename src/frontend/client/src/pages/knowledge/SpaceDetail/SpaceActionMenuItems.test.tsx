import { fireEvent, render, screen } from '@testing-library/react';
import { SpaceActionMenuItems, getSpaceActionFlags } from './SpaceActionMenuItems';
import type { KnowledgeSpace } from '~/api/knowledge';
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('bisheng-icons', () => ({ Outlined: new Proxy({}, { get: () => () => null }) }));
jest.mock('@bisheng/ui', () => ({
  DropdownItem: ({ children, onSelect }: { children: React.ReactNode; onSelect: () => void }) => <button onClick={onSelect}>{children}</button>,
  DropdownSeparator: () => null,
}));
const space = { id: 'joined', name: 'Joined' } as KnowledgeSpace;
it('prefers exit over elevated delete permissions in the detail action menu', () => {
  const onLeaveSpace = jest.fn();
  const onDeleteSpace = jest.fn();
  render(<SpaceActionMenuItems space={space} canDeleteSpace canLeaveSpace onLeaveSpace={onLeaveSpace} onDeleteSpace={onDeleteSpace} />);
  expect(screen.queryByText('com_knowledge.delete_space')).toBeNull();
  fireEvent.click(screen.getByText('com_knowledge.exit_space_short'));
  expect(onLeaveSpace).toHaveBeenCalledTimes(1);
  expect(onDeleteSpace).not.toHaveBeenCalled();
});
it('does not fall back to deletion when the exit callback is unavailable', () => {
  expect(getSpaceActionFlags({ space, canLeaveSpace: true, canDeleteSpace: true, onDeleteSpace: jest.fn() }).showDelete).toBe(false);
});
it('preserves deletion for created and department spaces', () => {
  const onDeleteSpace = jest.fn();
  render(<SpaceActionMenuItems space={space} canDeleteSpace onDeleteSpace={onDeleteSpace} />);
  fireEvent.click(screen.getByText('com_knowledge.delete_space'));
  expect(onDeleteSpace).toHaveBeenCalledTimes(1);
  expect(screen.queryByText('com_knowledge.exit_space_short')).toBeNull();
});
