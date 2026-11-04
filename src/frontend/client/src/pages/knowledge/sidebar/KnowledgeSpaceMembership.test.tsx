import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import KnowledgeSpaceItem from './KnowledgeSpaceItem';
import KnowledgeSpaceCardItem from './KnowledgeSpaceCardItem';

const mockConfirm = jest.fn().mockResolvedValue(true);
jest.mock('~/Providers', () => ({ useConfirm: () => mockConfirm }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/queries/data-provider', () => ({ useGetBsConfig: () => ({ data: {} }) }));
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn(), useParams: () => ({}) }));
jest.mock('bisheng-icons', () => ({ Outlined: new Proxy({}, { get: () => () => null }) }));
jest.mock('@bisheng/ui', () => ({
  Dropdown: ({ menu, children, open }: { menu: React.ReactNode; children: React.ReactNode; open?: boolean }) => <>{children}{open === false ? null : menu}</>,
  DropdownItem: ({ onSelect, children }: { onSelect: () => void; children: React.ReactNode }) => <button onClick={onSelect}>{children}</button>,
  DropdownSeparator: () => null,
}));
jest.mock('./KnowledgeFolderTree', () => ({ KnowledgeFolderTree: () => null }));
jest.mock('./DynamicEllipsisName', () => ({ DynamicEllipsisName: () => null }));
jest.mock('./KnowledgeSpaceFolderArt', () => ({ KnowledgeSpaceFolderArt: ({ children }: { children: React.ReactNode }) => <>{children}</> }));
jest.mock('~/utils', () => ({ cn: (...values: string[]) => values.filter(Boolean).join(' ') }));
jest.mock('../knowledgeUtils', () => ({ formatTimeCard: () => '' }));
jest.mock('~/components/illustrations', () => ({ KnowledgeSpaceIcon: () => null }));
jest.mock('~/components/ActionMenu', () => ({ ActionMenuLoadingRow: () => null }));
jest.mock('~/mock/demo/DemoTag', () => ({ DemoTag: () => null }));

it.each([KnowledgeSpaceItem, KnowledgeSpaceCardItem])('keeps the joined admin action, confirmation and request on leave', async Component => {
  const onDelete = jest.fn();
  const onLeave = jest.fn();
  render(<Component space={{ id: 'space', name: 'Joined' } as never} type="joined" isActive={false}
    canDeleteSpace onSelect={jest.fn()} onUpdate={jest.fn()} onDelete={onDelete} onLeave={onLeave} onPin={jest.fn()} />);
  fireEvent.click(screen.getByText('com_knowledge.exit_space_short'));
  await waitFor(() => expect(onLeave).toHaveBeenCalledWith('space'));
  expect(onDelete).not.toHaveBeenCalled();
  expect(mockConfirm).toHaveBeenLastCalledWith(expect.objectContaining({
    description: 'com_knowledge.confirm_exit_space', confirmText: 'com_knowledge.exit',
  }));
});

it.each([KnowledgeSpaceItem, KnowledgeSpaceCardItem])('keeps real deletion destructive and sends only the delete action', async Component => {
  const onDelete = jest.fn();
  const onLeave = jest.fn();
  render(<Component space={{ id: 'space', name: 'Created' } as never} type="created" isActive={false}
    canDeleteSpace onSelect={jest.fn()} onUpdate={jest.fn()} onDelete={onDelete} onLeave={onLeave} onPin={jest.fn()} />);
  fireEvent.click(screen.getByText('com_knowledge.delete_space'));
  await waitFor(() => expect(onDelete).toHaveBeenCalledWith('space'));
  expect(onLeave).not.toHaveBeenCalled();
  expect(mockConfirm).toHaveBeenLastCalledWith(expect.objectContaining({ variant: 'destructive' }));
});
