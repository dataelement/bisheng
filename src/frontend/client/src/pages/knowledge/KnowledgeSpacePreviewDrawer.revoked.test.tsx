import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode, ButtonHTMLAttributes } from 'react';
import {
    getSpaceInfoApi, getSpaceChildrenApi, getJoinedSpacesApi, subscribeSpaceApi,
    SpaceRole, VisibilityType,
} from '~/api/knowledge';
import type { KnowledgeSpace } from '~/api/knowledge';
import { checkResourceAction } from '~/api/permission';
import { KnowledgeSpacePreviewDrawer } from './KnowledgeSpacePreviewDrawer';

jest.mock('~/api/knowledge', () => ({
    SpaceRole: { CREATOR: 'creator', ADMIN: 'admin', MEMBER: 'member' },
    VisibilityType: { PUBLIC: 'public', PRIVATE: 'private', APPROVAL: 'approval' },
    SPACE_CHILDREN_STATUS_SUCCESS_ONLY: [1],
    getSpaceInfoApi: jest.fn(), getSpaceChildrenApi: jest.fn(), getJoinedSpacesApi: jest.fn(),
    subscribeSpaceApi: jest.fn(), unsubscribeSpaceApi: jest.fn(),
}));
jest.mock('~/api/permission', () => ({ checkResourceAction: jest.fn() }));
jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key, usePrefersMobileLayout: () => false,
    useScrollRevealRef: () => ({ current: null }),
}));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks/useEffectiveQuota', () => ({ useEffectiveQuota: () => ({ isOverQuota: () => false }) }));
jest.mock('~/utils', () => ({ cn: (...classes: string[]) => classes.filter(Boolean).join(' ') }));
jest.mock('~/components/illustrations', () => ({ EmptyStateIllustration: () => null, NoPermissionIllustration: () => null }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => null }));
jest.mock('~/components/ui/Sheet', () => ({
    Sheet: ({ open, children }: { open: boolean; children: ReactNode }) => open ? <div>{children}</div> : null,
    SheetContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SheetHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SheetTitle: ({ children }: { children: ReactNode }) => <h2>{children}</h2>,
}));
jest.mock('~/components/ui/Button', () => ({
    Button: ({ children, onClick, disabled }: ButtonHTMLAttributes<HTMLButtonElement>) => <button onClick={onClick} disabled={disabled}>{children}</button>,
}));
jest.mock('./SpaceDetail/FileCard', () => ({ FileCard: ({ file }: { file: { name: string } }) => <p>{file.name}</p> }));

const space: KnowledgeSpace = {
    id: '74', name: 'KS1030T46', visibility: VisibilityType.APPROVAL,
    creator: 'owner', creatorId: '1', memberCount: 2, fileCount: 1, totalFileCount: 1,
    role: SpaceRole.MEMBER, isPinned: false, createdAt: '', updatedAt: '', tags: [], isReleased: true,
    isFollowed: true, subscriptionStatus: 'subscribed', squareStatus: 'joined',
};

beforeEach(() => {
    jest.mocked(getSpaceInfoApi).mockResolvedValue(space);
    jest.mocked(getJoinedSpacesApi).mockResolvedValue([]);
    jest.mocked(getSpaceChildrenApi).mockResolvedValue({ data: [{ id: '1', name: 'KSP_VIEW_1031R.txt' }], has_more: false } as never);
    jest.mocked(checkResourceAction).mockResolvedValue({ allowed: false } as never);
    jest.mocked(subscribeSpaceApi).mockResolvedValue({ status: 'pending', spaceId: '74' });
});

it('permission denial replaces joined on the drawer and notifies the square, then allows reapplication', async () => {
    const onStatusChange = jest.fn();
    render(<KnowledgeSpacePreviewDrawer spaceId="74" open onOpenChange={jest.fn()} onSquareStatusChange={onStatusChange} />);
    const join = await screen.findByRole('button', { name: 'com_knowledge.join' });
    expect(join).toBeEnabled();
    expect(screen.getByText('com_knowledge.space_view_requires_approval')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'com_knowledge.joined' })).toBeNull();
    expect(onStatusChange).toHaveBeenLastCalledWith('74', 'join');
    expect(getSpaceChildrenApi).not.toHaveBeenCalled();
    fireEvent.click(join);
    await waitFor(() => expect(subscribeSpaceApi).toHaveBeenCalledWith('74'));
    expect(await screen.findByRole('button', { name: 'com_knowledge.pending' })).toBeDisabled();
    expect(onStatusChange).toHaveBeenLastCalledWith('74', 'pending');
});

it('fresh non-subscribed details replace a stale joined square card', async () => {
    jest.mocked(getSpaceInfoApi).mockResolvedValue({ ...space, isFollowed: false, subscriptionStatus: 'not_subscribed', squareStatus: 'join' });
    const onStatusChange = jest.fn();
    render(<KnowledgeSpacePreviewDrawer spaceId="74" initialSpace={space} open onOpenChange={jest.fn()} onSquareStatusChange={onStatusChange} />);
    expect(await screen.findByRole('button', { name: 'com_knowledge.join' })).toBeEnabled();
    expect(onStatusChange).toHaveBeenLastCalledWith('74', 'join');
});

it('current effective access keeps joined and loads the synthetic file', async () => {
    jest.mocked(checkResourceAction).mockResolvedValue({ allowed: true } as never);
    render(<KnowledgeSpacePreviewDrawer spaceId="74" open onOpenChange={jest.fn()} />);
    expect(await screen.findByText('KSP_VIEW_1031R.txt')).toBeVisible();
    expect(screen.getByRole('button', { name: 'com_knowledge.joined' })).toBeDisabled();
});

it.each(['pending', 'rejected'])('preserves the %s application state', async (status) => {
    jest.mocked(getSpaceInfoApi).mockResolvedValue({ ...space, isFollowed: false, subscriptionStatus: status, squareStatus: status as 'pending' | 'rejected' });
    render(<KnowledgeSpacePreviewDrawer spaceId="74" open onOpenChange={jest.fn()} />);
    const label = status === 'pending' ? 'com_knowledge.pending' : 'com_knowledge.reapply';
    const action = await screen.findByRole('button', { name: label });
    if (status === 'pending') expect(action).toBeDisabled();
    else expect(action).toBeEnabled();
    expect(subscribeSpaceApi).not.toHaveBeenCalled();
});

it('a permission-service error preserves membership instead of inventing a revocation', async () => {
    jest.mocked(checkResourceAction).mockRejectedValue(new Error('unavailable'));
    const onStatusChange = jest.fn();
    render(<KnowledgeSpacePreviewDrawer spaceId="74" open onOpenChange={jest.fn()} onSquareStatusChange={onStatusChange} />);
    await waitFor(() => expect(checkResourceAction).toHaveBeenCalled());
    expect(await screen.findByRole('button', { name: 'com_knowledge.joined' })).toBeDisabled();
    expect(onStatusChange).not.toHaveBeenCalledWith('74', 'join');
});
