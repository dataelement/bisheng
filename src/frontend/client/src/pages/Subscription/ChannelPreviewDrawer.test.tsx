import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ChannelPreviewDrawer } from './ChannelPreviewDrawer';
import { getArticlesApi, getChannelDetailApi, subscribeManagerChannelApi } from '~/api/channels';

jest.mock('react-activation', () => ({ useActivate: jest.fn(), useUnactivate: jest.fn() }));
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useScrollRevealRef: () => ({ current: null }) }));
jest.mock('~/hooks/AuthContext', () => ({ useAuthContext: () => ({ user: { username: 'viewer' } }) }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/api/channels', () => ({ getChannelDetailApi: jest.fn(), getArticlesApi: jest.fn(), subscribeManagerChannelApi: jest.fn() }));
jest.mock('~/common', () => ({ NotificationSeverity: { SUCCESS: 'success', WARNING: 'warning' } }));
jest.mock('~/components/illustrations', () => ({ NoPermissionIllustration: () => <div /> }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => <div /> }));
jest.mock('~/components/InfiniteScroll', () => ({ InfiniteScroll: ({ children }: React.PropsWithChildren) => <div>{children}</div> }));
jest.mock('~/components/ui/Sheet', () => ({
    Sheet: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
    SheetContent: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
    SheetHeader: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
    SheetTitle: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
}));
jest.mock('~/components/ui/Avatar', () => ({
    Avatar: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
    AvatarImage: () => <div />, AvatarName: () => <div />,
}));
jest.mock('~/components/ui/Tooltip2', () => ({
    Tooltip: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
    TooltipContent: () => <div />,
    TooltipTrigger: ({ children }: React.PropsWithChildren) => <div>{children}</div>,
}));
jest.mock('~/components/ui/Button', () => ({ Button: ({ children, disabled, onClick }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button disabled={disabled} onClick={onClick}>{children}</button> }));
jest.mock('./ArticleList/ArticleCard', () => ({ ArticleCard: () => <div>Article content</div> }));
jest.mock('./ArticleList/ArticleList', () => ({ mapToArticle: (article: unknown) => article }));

function mountDrawer() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
    const view = render(<QueryClientProvider client={client}><ChannelPreviewDrawer channelId="c1" open onOpenChange={jest.fn()} /></QueryClientProvider>);
    return { client, ...view };
}

it('shows approval and revocation from fresh server data while the drawer stays open', async () => {
    let detail = { id: 'c1', name: 'News', creator_name: 'owner', subscription_status: 'not_subscribed', visibility: 'review' as const, actions: [] as string[], source_infos: [], article_count: 1, subscriber_count: 1 };
    jest.mocked(getChannelDetailApi).mockImplementation(async () => ({ ...detail, source_list: [], is_released: true }));
    jest.mocked(subscribeManagerChannelApi).mockImplementation(async () => { detail = { ...detail, subscription_status: 'pending' }; return 'pending'; });
    jest.mocked(getArticlesApi).mockResolvedValue({ data: [{ id: 'a1' }], total: 1 } as never);
    const { client, unmount } = mountDrawer();
    fireEvent.click(await screen.findByRole('button', { name: 'com_subscription.subscribe' }));
    expect(await screen.findByRole('button', { name: 'com_subscription.applying' })).toBeDisabled();
    expect(getArticlesApi).toHaveBeenCalledTimes(0);
    detail = { ...detail, subscription_status: 'subscribed', actions: ['visible'] };
    act(() => { window.dispatchEvent(new Event('focus')); });
    expect(await screen.findByRole('button', { name: 'com_subscription.subscribed' })).toBeDisabled();
    await screen.findByText('Article content');
    detail = { ...detail, subscription_status: 'not_subscribed', actions: [] };
    act(() => { window.dispatchEvent(new Event('focus')); });
    expect(await screen.findByRole('button', { name: 'com_subscription.subscribe' })).toBeEnabled();
    await waitFor(() => expect(screen.queryByText('Article content')).toBeNull());
    expect(screen.getByText('com_subscription.channel_content_access_required')).toBeVisible();
    unmount(); client.clear();
});
