/* eslint-disable no-restricted-syntax -- CJK fixtures exercise the menu-name width limit. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AppCenter } from './AppCenter';

const mocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn(), reload: vi.fn(), t: (key: string) => key }));
vi.mock('@/controllers/API', () => ({ getDailyConfigApi: mocks.get, setDailyConfigApi: mocks.save }));
vi.mock('@/controllers/request', () => ({ handleUiRequest: (handler: () => unknown) => handler, showApiError: vi.fn() }));
vi.mock('@/contexts/locationContext', async () => {
    const { createContext } = await import('react');
    return { locationContext: createContext({ reloadConfig: mocks.reload }) };
});
vi.mock('i18next', () => ({ default: { loadLanguages: async () => undefined, getFixedT: () => (key: string) => key } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('./ConfigInheritanceBanner', () => ({ default: () => null, resolveConfigEnvelope: (data: unknown) => ({ data, meta: {} }) }));

describe('menu name saving', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.get.mockResolvedValue({ appCenterMenuDisplayName: 'Apps' });
        mocks.save.mockResolvedValue(true);
    });

    it('does not send an oversized name, then saves after correction', async () => {
        render(<AppCenter />);
        const input = screen.getByRole('textbox', { name: 'chatConfig.menuDisplayName' });
        await waitFor(() => expect(input).toHaveValue('Apps'));
        fireEvent.change(input, { target: { value: '我的应用中心' } });
        expect(input).toHaveValue('我的应用中心');
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        expect(screen.getByText('chatConfig.menuNameTooLong')).toBeInTheDocument();
        expect(mocks.save).not.toHaveBeenCalled();
        fireEvent.change(input, { target: { value: '我的应用' } });
        expect(screen.queryByText('chatConfig.menuNameTooLong')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'save' }));
        await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(expect.objectContaining({ appCenterMenuDisplayName: '我的应用' })));
    });

    it('does not render a character counter', async () => {
        render(<AppCenter />);
        await waitFor(() => expect(screen.getByRole('textbox', { name: 'chatConfig.menuDisplayName' })).toHaveValue('Apps'));
        expect(screen.queryByText(/\d\s*\/\s*8/)).not.toBeInTheDocument();
    });
});
