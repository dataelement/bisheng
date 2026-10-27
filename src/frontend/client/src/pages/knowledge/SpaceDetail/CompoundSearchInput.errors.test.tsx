import i18next from 'i18next';
import messages from '../../../locales/en/api_errors.gen.json';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { normalizeApiError } from '@bisheng/api-client';
import { getSpaceTagsApi } from '~/api/knowledge';
import { CompoundSearchInput } from './CompoundSearchInput';

jest.mock('~/api/knowledge', () => ({ getSpaceTagsApi: jest.fn() }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));

beforeAll(async () => { await i18next.init({ lng: 'en', resources: { en: { translation: { api_errors: messages } } } }); });
const getTags = jest.mocked(getSpaceTagsApi);
const notify = jest.fn();

beforeEach(() => {
    getTags.mockReset().mockResolvedValue([]);
    window.showToast = notify;
});

it('reports a failed tag request and can load tags on the next interaction', async () => {
    getTags.mockRejectedValueOnce(normalizeApiError({ code: 'ERR_NETWORK' }, { message: 'Tags unavailable' }));
    render(<CompoundSearchInput spaceId="one" isRoot pageMode />);
    await waitFor(() => expect(notify).toHaveBeenCalledWith(expect.objectContaining({ message: messages.network_error })));

    getTags.mockResolvedValueOnce([{ id: 1, name: 'Reports' }]);
    fireEvent.focus(screen.getByRole('textbox'));
    expect(await screen.findByRole('button', { name: 'Reports' })).toBeInTheDocument();
});

it.each(['canceled', 'global'] as const)('does not duplicate feedback for a %s request', async kind => {
    const error = normalizeApiError(kind === 'canceled' ? { code: 'ERR_CANCELED' } : { status_code: 500 }, { message: 'Already handled' });
    if (kind === 'global') error.presentation = 'global';
    getTags.mockRejectedValueOnce(error);
    await act(async () => { render(<CompoundSearchInput spaceId="one" isRoot pageMode />); });
    expect(notify).not.toHaveBeenCalled();
});

it('ignores a failed request from the space that has already been left', async () => {
    let failOldRequest!: (reason: unknown) => void;
    getTags.mockReturnValueOnce(new Promise((_resolve, reject) => { failOldRequest = reject; }));
    const view = render(<CompoundSearchInput spaceId="one" isRoot pageMode />);
    getTags.mockResolvedValueOnce([{ id: 2, name: 'Current tags' }]);
    view.rerender(<CompoundSearchInput spaceId="two" isRoot pageMode />);
    await screen.findByRole('button', { name: 'Current tags' });
    await act(async () => { failOldRequest(new Error('Old space failed')); });
    expect(notify).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Current tags' })).toBeInTheDocument();
});
