import React from 'react';
import { fireEvent, render } from '@testing-library/react';
import { SidebarConversationList } from './SidebarConversationList';

const mockFetchNextPage = jest.fn();
const mockProjects = {};
const mockData = { pages: [{ conversations: [{ conversationId: 'one', title: 'First chat' }] }] };
jest.mock('~/hooks', () => ({
  useAuthContext: () => ({ isAuthenticated: true }),
  useLocalize: () => (key: string) => key,
  useNavScrolling: jest.requireActual('~/hooks/Nav/useNavScrolling').default,
  useScrollRevealRef: jest.requireActual('~/hooks/useScrollRevealRef').useScrollRevealRef,
}));
jest.mock('~/hooks/queries/data-provider', () => ({
  useConversationsInfiniteQuery: () => ({ data: mockData, fetchNextPage: mockFetchNextPage, hasNextPage: true, isFetchingNextPage: false }),
}));
jest.mock('./projectsStore', () => ({ useMockProjectChats: () => mockProjects }));
jest.mock('~/components/Conversations/Convo', () => ({ __esModule: true, default: () => <div>First chat</div> }));
jest.mock('~/components/svg', () => ({ Spinner: () => <span>Loading</span> }));
jest.mock('~/utils', () => ({ cn: (...values: string[]) => values.filter(Boolean).join(' ') }));

it('reveals the workbench history scrollbar on scroll, keeps pagination and hides after idle', () => {
  jest.useFakeTimers();
  try {
    const { container, unmount } = render(<SidebarConversationList leading={<div>Projects</div>} />);
    const scroller = container.querySelector<HTMLDivElement>('.scrollbar-on-scroll');
    expect(scroller).not.toBeNull();
    expect(scroller).not.toHaveClass('scroll-no-hover');
    fireEvent.mouseEnter(scroller!);
    expect(scroller).not.toHaveAttribute('data-scrolling');
    Object.defineProperties(scroller, { scrollHeight: { value: 1000 }, clientHeight: { value: 200 }, scrollTop: { value: 900 } });
    fireEvent.scroll(scroller!);
    expect(scroller).toHaveAttribute('data-scrolling', 'true');
    expect(mockFetchNextPage).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(700);
    expect(scroller).not.toHaveAttribute('data-scrolling');
    unmount();
  } finally {
    jest.useRealTimers();
  }
});
