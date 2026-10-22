import { normalizeApiError } from '@bisheng/api-client';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AudioPlayComponent } from './audioPlayButton';

const mock = vi.hoisted(() => ({ tts: vi.fn(), report: vi.fn(), notice: vi.fn(), loading: vi.fn(), current: vi.fn(), play: vi.fn() }));
vi.mock('@/controllers/API/workbench', () => ({ textToSpeech: mock.tts }));
vi.mock('@/controllers/request', () => ({ showApiError: mock.report }));
vi.mock('@bisheng/ui', () => ({ notification: { open: mock.notice } }));
vi.mock('./audioPlayerStore', () => ({ useAudioPlayerStore: () => ({
    currentPlayingId: null, soundInstance: null, isLoading: false, playAudio: mock.play,
    pauseAudio: vi.fn(), resumeAudio: vi.fn(), stopAudio: vi.fn(), setLoading: mock.loading, setCurrentPlayingId: mock.current,
}) }));
beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

it('delegates the original TTS ApiError and releases loading/playback ownership', async () => {
    const error = normalizeApiError(new Error('TTS failed'), { message: 'TTS failed' });
    error.presentation = 'global';
    mock.tts.mockRejectedValueOnce(error);
    render(<AudioPlayComponent messageId="m1" msg="Hello" />);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await waitFor(() => expect(mock.current).toHaveBeenLastCalledWith(null));
    expect(mock.loading).toHaveBeenLastCalledWith(false);
    expect(mock.report).toHaveBeenCalledWith(error);
    expect(mock.notice).not.toHaveBeenCalled();
});

it('keeps the existing local playback error copy and releases resources', async () => {
    mock.tts.mockResolvedValueOnce('/audio.wav');
    mock.play.mockImplementationOnce(() => { throw new Error('Device unavailable'); });
    render(<AudioPlayComponent messageId="m1" msg="Hello" />);
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    await waitFor(() => expect(mock.current).toHaveBeenLastCalledWith(null));
    expect(mock.notice).toHaveBeenCalledWith(expect.objectContaining({ description: 'playbackUnavailable' }));
    expect(mock.report).not.toHaveBeenCalled();
});
