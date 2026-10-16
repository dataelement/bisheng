/** @jest-environment jsdom */
import { renderHook } from '@testing-library/react';
import { useDesktopConversation } from './useDesktopConversation';

let mockPathname = '/c/new';
jest.mock('react-router-dom', () => ({ useLocation: () => ({ pathname: mockPathname }) }));
afterEach(() => { delete window.dshChatPresentation; mockPathname = '/c/new'; });

it('publishes optimistic conversation state before the server changes the new route', () => {
  const reportLanding = jest.fn();
  window.dshChatPresentation = { reportLanding };
  const { rerender } = renderHook(({ landing }) => useDesktopConversation('new', landing), { initialProps: { landing: true } });
  expect(reportLanding).toHaveBeenLastCalledWith(true);
  rerender({ landing: false });
  expect(reportLanding).toHaveBeenLastCalledWith(false);
  expect(mockPathname).toBe('/c/new');
  rerender({ landing: true });
  expect(reportLanding).toHaveBeenLastCalledWith(true);
});

it('keeps cached views silent on other routes and supports standalone web pages', () => {
  const reportLanding = jest.fn();
  window.dshChatPresentation = { reportLanding };
  mockPathname = '/linsight/task';
  const { rerender } = renderHook(({ landing }) => useDesktopConversation('new', landing), { initialProps: { landing: true } });
  rerender({ landing: false });
  expect(reportLanding).toHaveBeenCalledTimes(0);
  mockPathname = '/c/new';
  delete window.dshChatPresentation;
  rerender({ landing: true });
});
