import { act, renderHook } from '@testing-library/react';
import { getRunQueuePosition } from '~/api/runApi';
import { POLL_INTERVAL_MS, useRunQueuePosition } from './useRunQueuePosition';

jest.mock('~/api/runApi', () => ({ getRunQueuePosition: jest.fn() }));

const mockPosition = getRunQueuePosition as jest.MockedFunction<typeof getRunQueuePosition>;

async function flush() {
    await act(async () => {
        await Promise.resolve();
    });
}

beforeEach(() => {
    jest.useFakeTimers();
    mockPosition.mockReset();
});

afterEach(() => {
    jest.useRealTimers();
});

test('asks for the position while enabled and follows it as the queue moves', async () => {
    mockPosition.mockResolvedValueOnce(3).mockResolvedValueOnce(1).mockResolvedValue(null);
    const { result } = renderHook(() => useRunQueuePosition('c1', true));

    await flush();
    expect(result.current).toBe(3);
    expect(mockPosition).toHaveBeenCalledWith('c1');

    await act(async () => {
        jest.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    expect(result.current).toBe(1);

    await act(async () => {
        jest.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    // The worker took the run: no position any more.
    expect(result.current).toBeNull();
});

test('a failed request keeps the last position and asks again', async () => {
    mockPosition.mockResolvedValueOnce(2).mockRejectedValueOnce(new Error('network')).mockResolvedValue(2);
    const { result } = renderHook(() => useRunQueuePosition('c1', true));

    await flush();
    await act(async () => {
        jest.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    expect(result.current).toBe(2);
    expect(mockPosition).toHaveBeenCalledTimes(2);

    await act(async () => {
        jest.advanceTimersByTime(POLL_INTERVAL_MS);
    });
    await flush();
    expect(mockPosition).toHaveBeenCalledTimes(3);
});

test('asks nothing when disabled or for an unsaved conversation, and stops when disabled', async () => {
    mockPosition.mockResolvedValue(4);
    renderHook(() => useRunQueuePosition('c1', false));
    renderHook(() => useRunQueuePosition('new', true));
    await flush();
    expect(mockPosition).not.toHaveBeenCalled();

    const { result, rerender } = renderHook(({ on }) => useRunQueuePosition('c2', on), { initialProps: { on: true } });
    await flush();
    expect(result.current).toBe(4);

    rerender({ on: false });
    expect(result.current).toBeNull();
    await act(async () => {
        jest.advanceTimersByTime(POLL_INTERVAL_MS * 3);
    });
    expect(mockPosition).toHaveBeenCalledTimes(1);
});
