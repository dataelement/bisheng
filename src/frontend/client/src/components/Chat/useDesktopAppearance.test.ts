import { act, renderHook, waitFor } from '@testing-library/react';
import { useDesktopAppearance } from './useDesktopAppearance';

beforeEach(() => {
  window.history.replaceState({}, '', '/');
  document.documentElement.className = 'light';
  delete document.documentElement.dataset.dshHostTheme;
  window.matchMedia = jest.fn().mockReturnValue({ matches: true, addEventListener: jest.fn(), removeEventListener: jest.fn() });
});

test('standalone Chat follows the page preference and live theme changes', async () => {
  const view = renderHook(useDesktopAppearance);
  expect(document.body.dataset.dshChatTheme).toBe('light');
  act(() => { document.documentElement.className = 'dark'; });
  await waitFor(() => expect(document.body.dataset.dshChatTheme).toBe('dark'));
  act(() => { document.documentElement.className = 'light'; });
  await waitFor(() => expect(document.body.dataset.dshChatTheme).toBe('light'));
  view.unmount();
  expect(document.body.dataset.dshChatTheme).toBeUndefined();
});

test('embedded Chat uses the host theme for content and portalled controls', async () => {
  window.history.replaceState({}, '', '/?embed=dsh');
  document.documentElement.dataset.dshHostTheme = 'dark';
  const view = renderHook(useDesktopAppearance);
  expect(document.body.dataset.dshChatTheme).toBe('dark');
  expect(document.documentElement).toHaveClass('dark');
  act(() => window.dispatchEvent(new CustomEvent('dsh:appearance', { detail: { theme: 'light' } })));
  expect(document.body.dataset.dshChatTheme).toBe('light');
  expect(document.documentElement).toHaveClass('light');
  act(() => window.dispatchEvent(new CustomEvent('dsh:appearance', { detail: { theme: 'invalid' } })));
  expect(document.body.dataset.dshChatTheme).toBe('light');
  view.unmount();
});
