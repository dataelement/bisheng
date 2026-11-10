import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import ChannelSquare from './ChannelSquare';
import { getChannelSquareApi } from '~/api/channels';

jest.mock('react-activation', () => ({ useActivate: jest.fn(), useUnactivate: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useMediaQuery: () => false }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/api/channels', () => ({ getChannelSquareApi: jest.fn(), getChannelDetailApi: jest.fn(), subscribeManagerChannelApi: jest.fn() }));
jest.mock('~/common', () => ({ NotificationSeverity: { SUCCESS: 'success', WARNING: 'warning' } }));
jest.mock('~/components/illustrations', () => ({ EmptyStateIllustration: () => <div /> }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => <div /> }));
jest.mock('bisheng-icons', () => ({ Outlined: { Plus: () => <div />, SidebarMenu: () => <div /> } }));
jest.mock('@bisheng/ui', () => ({ SearchInput: () => <input /> }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('./ChannelSquareCard', () => ({ ChannelSquareCard: ({ title, status }: { title: string; status: string }) => <div>{title}:{status}</div> }));

beforeEach(() => {
    window.IntersectionObserver = jest.fn(() => ({ observe: jest.fn(), disconnect: jest.fn(), unobserve: jest.fn() })) as unknown as typeof IntersectionObserver;
});

it('refreshes every loaded page on focus and keeps the list visible during the request', async () => {
    let status = 'pending';
    let release: (() => void) | undefined;
    let pause: Promise<void> = Promise.resolve();
    jest.mocked(getChannelSquareApi).mockImplementation(async ({ page } = {}) => {
        await pause;
        return { data: { data: [{ id: `c${page}`, name: `Channel ${page}`, visibility: 'review', subscription_status: status, source_infos: [] }], total: 2 } };
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container, unmount } = render(<QueryClientProvider client={client}><ChannelSquare /></QueryClientProvider>);
    await screen.findByText('Channel 1:pending');
    const scroll = container.querySelector('.overflow-y-auto');
    expect(scroll).toBeTruthy();
    fireEvent.scroll(scroll!);
    await screen.findByText('Channel 2:pending');
    pause = new Promise<void>((resolve) => { release = resolve; });
    status = 'subscribed';
    act(() => { window.dispatchEvent(new Event('focus')); });
    expect(screen.getByText('Channel 1:pending')).toBeVisible();
    expect(screen.getByText('Channel 2:pending')).toBeVisible();
    await act(async () => { release?.(); });
    await screen.findByText('Channel 1:joined');
    await screen.findByText('Channel 2:joined');
    await waitFor(() => expect(getChannelSquareApi).toHaveBeenCalledTimes(4));
    unmount(); client.clear();
});
