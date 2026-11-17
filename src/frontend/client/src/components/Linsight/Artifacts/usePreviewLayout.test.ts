import { act, renderHook } from '@testing-library/react';
import { usePreviewLayout } from './usePreviewLayout';

describe('artifact preview layout', () => {
    const originalObserver = window.ResizeObserver;
    let scroller: HTMLDivElement;
    let root: HTMLDivElement;
    let width: number;
    let height: number;
    let resize: () => void;
    const disconnect = jest.fn();

    beforeEach(() => {
        jest.useFakeTimers();
        width = height = 0;
        scroller = document.createElement('div');
        scroller.style.overflowY = 'auto';
        root = document.createElement('div');
        scroller.appendChild(root);
        document.body.appendChild(scroller);
        Object.defineProperties(scroller, {
            clientWidth: { get: () => width },
            clientHeight: { get: () => height },
        });
        window.ResizeObserver = jest.fn().mockImplementation((callback) => {
            resize = () => callback([], {});
            return { observe: jest.fn(), disconnect };
        });
        jest.spyOn(window, 'requestAnimationFrame').mockImplementation(
            (callback) => window.setTimeout(() => callback(0), 16),
        );
        jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(window.clearTimeout);
    });

    afterEach(() => {
        scroller.remove();
        window.ResizeObserver = originalObserver;
        jest.restoreAllMocks();
        jest.useRealTimers();
    });

    const settle = () => act(() => { jest.advanceTimersByTime(150); });

    it('refreshes after an ancestor animation but ignores document button animations', () => {
        width = 480;
        height = 700;
        const ref = { current: root };
        const { result } = renderHook(() => usePreviewLayout(ref));
        settle();
        const button = document.createElement('button');
        root.appendChild(button);
        act(() => button.dispatchEvent(new Event('transitionend', { bubbles: true })));
        settle();
        expect(result.current).toBe(1);
        act(() => scroller.dispatchEvent(new Event('transitionend', { bubbles: true })));
        settle();
        expect(result.current).toBe(2);
    });

    it('waits for the hidden drawer to acquire dimensions', () => {
        const ref = { current: root };
        const { result } = renderHook(() => usePreviewLayout(ref));
        settle();
        expect(result.current).toBe(0);
        width = 480;
        height = 700;
        act(() => resize());
        settle();
        expect(result.current).toBe(1);
    });

    it('rebuilds once after fullscreen resizing settles, not on every frame', () => {
        width = 480;
        height = 700;
        const ref = { current: root };
        const { result } = renderHook(() => usePreviewLayout(ref));
        settle();
        for (const next of [600, 800, 1000]) {
            act(() => {
                width = next;
                resize();
                jest.advanceTimersByTime(30);
            });
        }
        expect(result.current).toBe(1);
        settle();
        expect(result.current).toBe(2);
        act(() => resize());
        settle();
        expect(result.current).toBe(2);
    });

    it('cancels a pending document rebuild when the preview closes', () => {
        width = 480;
        height = 700;
        const ref = { current: root };
        const { result, unmount } = renderHook(() => usePreviewLayout(ref));
        unmount();
        settle();
        expect(result.current).toBe(0);
        expect(disconnect).toHaveBeenCalled();
    });
});
