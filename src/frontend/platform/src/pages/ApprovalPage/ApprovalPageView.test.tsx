import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ComponentProps } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { ApprovalPageView } from './ApprovalPageView';

vi.mock('./ApprovalDialogs', () => ({ ApprovalDialogs: () => null }));
vi.mock('./FlowManagementPanel', () => ({ FlowManagementPanel: () => null }));
vi.mock('./ExceptionPanel', () => ({ ExceptionPanel: () => null }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));

afterEach(() => {
  cleanup();
  document.getElementById('approval-header-menu')?.remove();
});

it('renders a large segmented selector in the header and preserves section switching', () => {
  const header = document.createElement('div');
  header.id = 'approval-header-menu';
  document.body.appendChild(header);
  const setActiveTab = vi.fn();
  const loadPage = vi.fn().mockResolvedValue(undefined);
  const controller = {
    t: (key: string) => key,
    activeTab: 'flow',
    setActiveTab,
    loadPage,
    loadError: null,
  } as unknown as ComponentProps<typeof ApprovalPageView>['controller'];
  const { container } = render(<ApprovalPageView controller={controller} />);

  expect(header.contains(screen.getByRole('radiogroup'))).toBe(true);
  expect(container.querySelector('[role="radiogroup"]')).toBeNull();
  expect(screen.queryByRole('tablist')).toBeNull();
  fireEvent.click(screen.getByRole('radio', { name: 'approvalPage.tabException' }));
  expect(setActiveTab).toHaveBeenCalledWith('exception');
  expect(loadPage).toHaveBeenCalledOnce();
});
