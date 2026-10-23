import { normalizeApiError } from '@bisheng/api-client';
import { beforeEach, expect, it, vi } from 'vitest';
import request from '../request';
import { previewFileSplitApi } from './index';

vi.mock('../request', () => ({ default: { get: vi.fn(), post: vi.fn() } }));
beforeEach(() => vi.clearAllMocks());

it.each(['create', 'poll'] as const)('passes the original %s request failure through the preview callback', async (stage) => {
    const cause = new Error('ASR rejected');
    const error = normalizeApiError(cause, { message: 'ASR rejected', envelope: {
        status_code: 10954, data: { exception: 'ASR request failed' },
    } });
    error.presentation = 'toast';
    if (stage === 'create') vi.mocked(request.post).mockRejectedValueOnce(error);
    else {
        vi.mocked(request.post).mockResolvedValueOnce({ preview_file_id: 'preview-1' });
        vi.mocked(request.get).mockRejectedValueOnce(error);
    }
    const onEvent = vi.fn();
    const cancel = previewFileSplitApi({}, onEvent);
    await vi.waitFor(() => expect(onEvent).toHaveBeenCalledWith('error', error));
    expect(onEvent.mock.calls[0][1]).toBe(error);
    expect(onEvent.mock.calls[0][1].cause).toBe(cause);
    cancel();
});

it('keeps cancellation silent on the callback error channel', async () => {
    const error = normalizeApiError({ code: 'ERR_CANCELED' }, { message: 'Canceled' });
    vi.mocked(request.post).mockRejectedValueOnce(error);
    const onEvent = vi.fn();
    const cancel = previewFileSplitApi({}, onEvent);
    await vi.waitFor(() => expect(request.post).toHaveBeenCalled());
    expect(onEvent).not.toHaveBeenCalled();
    cancel();
});
