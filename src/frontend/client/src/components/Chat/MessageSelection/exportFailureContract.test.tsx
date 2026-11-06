import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { normalizeApiError } from '@bisheng/api-client';
import { exportMessagesApi, triggerBrowserDownload } from '~/api/messageExport';
import { showApiError } from '~/api/request';
import { ExportFormatSheet } from './ExportFormatSheet';
import { MessageSelectionToolbar } from './MessageSelectionToolbar';
const mockToast = jest.fn();
const localize = (key: string) => key;
jest.mock('~/hooks', () => ({ useLocalize: () => localize }));
jest.mock('~/hooks/usePrefersMobileLayout', () => ({ __esModule: true, default: () => false }));
jest.mock('~/hooks/useMessageSelection', () => ({ useMessageSelection: () => ({ state: { active: true, chatId: 'chat' }, getSelectedIds: () => ['1'], isOverLimit: () => false, setGlobalSelectAll: jest.fn(), exitSelectionMode: jest.fn() }) }));
jest.mock('~/api/messageExport', () => ({ exportMessagesApi: jest.fn(), triggerBrowserDownload: jest.fn() }));
jest.mock('~/api/request', () => ({ showApiError: jest.fn(), translateApiErrorMessage: jest.fn(() => '') }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: mockToast }) }));
jest.mock('~/utils', () => ({ cn: (...v: unknown[]) => v.filter(Boolean).join(' ') }));
jest.mock('~/components/ui/Sheet', () => ({ Sheet: ({ children }: { children: React.ReactNode }) => <>{children}</>, SheetContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>, SheetHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>, SheetTitle: ({ children }: { children: React.ReactNode }) => <div>{children}</div> }));
const messages = [{ messageId: '1', isCreatedByUser: true }];
beforeEach(() => { jest.clearAllMocks(); (exportMessagesApi as jest.Mock).mockReset(); (triggerBrowserDownload as jest.Mock).mockReset(); });
describe.each(['toolbar', 'sheet'])('%s export endpoint', surface => {
  const mount = () => {
    const close = jest.fn();
    render(surface === 'toolbar' ? <MessageSelectionToolbar chatId="chat" messages={messages} onImportToKnowledge={jest.fn()} /> : <ExportFormatSheet chatId="chat" messages={messages} open onOpenChange={close} />);
    return close;
  };
  it.each(['business', 'global', 'canceled'])('hands the full %s error to its presentation owner and restores the button', async kind => {
    const error = normalizeApiError(kind === 'canceled' ? { code: 'ERR_CANCELED' } : { status_code: 19403, data: { used_gb: 4, quota_gb: 4 } }, { message: 'Export unavailable' });
    if (kind === 'global') error.presentation = 'global';
    (exportMessagesApi as jest.Mock).mockRejectedValue(error);
    const close = mount();
    fireEvent.click(screen.getByRole('button', { name: 'workstation.messageExport.exportAsWord' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'workstation.messageExport.exportAsWord' })).toBeEnabled());
    expect(showApiError).toHaveBeenCalledWith(error);
    expect((showApiError as jest.Mock).mock.calls[0][0]).toBe(error);
    expect(mockToast).not.toHaveBeenCalled();
    expect(triggerBrowserDownload).not.toHaveBeenCalled();
    expect(close).not.toHaveBeenCalled();
  });
  it('retains the localized fallback for a local download failure', async () => {
    (exportMessagesApi as jest.Mock).mockResolvedValue({ filename: 'chat.docx' });
    (triggerBrowserDownload as jest.Mock).mockImplementation(() => { throw new Error('browser download unavailable'); });
    mount();
    fireEvent.click(screen.getByRole('button', { name: 'workstation.messageExport.exportAsWord' }));
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({ message: 'workstation.messageExport.renderFailed' })));
    expect(showApiError).not.toHaveBeenCalled();
  });
  it('downloads successfully and closes only the successful sheet', async () => {
    const file = { filename: 'chat.docx' };
    (exportMessagesApi as jest.Mock).mockResolvedValue(file);
    const close = mount();
    fireEvent.click(screen.getByRole('button', { name: 'workstation.messageExport.exportAsWord' }));
    await waitFor(() => expect(triggerBrowserDownload).toHaveBeenCalledWith(file));
    expect(close.mock.calls).toEqual(surface === 'sheet' ? [[false]] : []);
    expect(mockToast).not.toHaveBeenCalled();
  });
});
