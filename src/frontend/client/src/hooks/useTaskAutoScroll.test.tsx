import { act, fireEvent, render, screen } from '@testing-library/react';
import { useTaskAutoScroll } from './useTaskAutoScroll';

let mockActivate: () => void;
let mockDeactivate: () => void;
jest.mock('react-activation', () => ({
    useActivate: (callback: () => void) => { mockActivate = callback; },
    useUnactivate: (callback: () => void) => { mockDeactivate = callback; },
}));

const resizeCallbacks = new Set<() => void>();
const originalResizeObserver = global.ResizeObserver;

function TaskMessages({ sessionKey = 'a', ready = true, enabled = true }) {
    const { containerRef, contentRef, showScrollButton, scrollToBottom } = useTaskAutoScroll({ sessionKey, enabled });
    return (
        <>
            {ready && <div data-testid="scroller" ref={containerRef}><div ref={contentRef}>Task output</div></div>}
            {showScrollButton && <button onClick={scrollToBottom}>Latest output</button>}
        </>
    );
}

// jsdom does not lay out elements. Supply browser geometry while keeping the
// actual DOM, scroll events, hook effects and observer callbacks in the test.
function setGeometry(height = 1000, viewport = 400) {
    const element = screen.getByTestId('scroller');
    const geometry = { height, viewport };
    Object.defineProperties(element, {
        scrollHeight: { configurable: true, get: () => geometry.height },
        clientHeight: { configurable: true, get: () => geometry.viewport },
    });
    element.scrollTo = (optionsOrX?: ScrollToOptions | number, y?: number) => {
        const top = typeof optionsOrX === 'number' ? y : optionsOrX?.top;
        element.scrollTop = Math.max(0, Math.min(top ?? 0, geometry.height - geometry.viewport));
    };
    return { element, geometry };
}

function flushLayout() {
    act(() => {
        resizeCallbacks.forEach((callback) => callback());
        jest.advanceTimersByTime(20);
    });
}

beforeEach(() => {
    jest.useFakeTimers();
    global.ResizeObserver = class implements ResizeObserver {
        callback: () => void;
        constructor(callback: ResizeObserverCallback) {
            this.callback = () => callback([], this);
            resizeCallbacks.add(this.callback);
        }
        observe() {}
        unobserve() {}
        disconnect() { resizeCallbacks.delete(this.callback); }
    };
});

afterEach(() => {
    resizeCallbacks.clear();
    global.ResizeObserver = originalResizeObserver;
    jest.useRealTimers();
});

it('follows a historical task whose scroll container mounts after loading', () => {
    const { rerender } = render(<TaskMessages ready={false} />);
    rerender(<TaskMessages ready />);
    const { element } = setGeometry();
    flushLayout();
    expect(element.scrollTop).toBe(600);
});

it('keeps following when asynchronous thought and tool children increase the height', () => {
    render(<TaskMessages />);
    const { element, geometry } = setGeometry();
    flushLayout();
    geometry.height = 1800;
    fireEvent.scroll(element);
    flushLayout();
    expect(element.scrollTop).toBe(1400);
    geometry.height = 2600;
    flushLayout();
    expect(element.scrollTop).toBe(2200);
});

it('lets the reader scroll up during output and resume with the bottom button', () => {
    render(<TaskMessages />);
    const { element, geometry } = setGeometry();
    flushLayout();
    fireEvent.wheel(element, { deltaY: -100 });
    element.scrollTop = 200;
    fireEvent.scroll(element);
    geometry.height = 1800;
    flushLayout();
    expect(element.scrollTop).toBe(200);
    fireEvent.click(screen.getByRole('button', { name: 'Latest output' }));
    flushLayout();
    expect(element.scrollTop).toBe(1400);
    geometry.height = 2200;
    flushLayout();
    expect(element.scrollTop).toBe(1800);
});

it('releases follow for an upward touch even when it starts during a content resize', () => {
    render(<TaskMessages />);
    const { element, geometry } = setGeometry();
    flushLayout();
    geometry.height = 1800;
    fireEvent.touchStart(element, { touches: [{ clientY: 100 }] });
    fireEvent.touchMove(element, { touches: [{ clientY: 200 }] });
    element.scrollTop = 400;
    fireEvent.scroll(element);
    flushLayout();
    expect(element.scrollTop).toBe(400);
});

it('lets the reader drag the scrollbar up while asynchronous content grows', () => {
    render(<TaskMessages />);
    const { element, geometry } = setGeometry();
    flushLayout();
    geometry.height = 1800;
    element.scrollTop = 200;
    fireEvent.scroll(element);
    flushLayout();
    expect(element.scrollTop).toBe(200);
});

it('reattaches when the reader scrolls back down to the latest output', () => {
    render(<TaskMessages />);
    const { element, geometry } = setGeometry();
    flushLayout();
    element.scrollTop = 100;
    fireEvent.scroll(element);
    element.scrollTop = 600;
    fireEvent.scroll(element);
    geometry.height = 1800;
    flushLayout();
    expect(element.scrollTop).toBe(1400);
});

it('resets a previous conversation reading position when switching sessions', () => {
    const { rerender } = render(<TaskMessages />);
    const { element } = setGeometry();
    flushLayout();
    element.scrollTop = 100;
    fireEvent.scroll(element);
    rerender(<TaskMessages sessionKey="b" />);
    flushLayout();
    expect(element.scrollTop).toBe(600);
});

it('follows output on KeepAlive return without scrolling an inactive conversation', () => {
    render(<TaskMessages />);
    const { element, geometry } = setGeometry();
    flushLayout();
    act(() => mockDeactivate());
    geometry.height = 1800;
    flushLayout();
    expect(element.scrollTop).toBe(600);
    act(() => mockActivate());
    flushLayout();
    expect(element.scrollTop).toBe(1400);
});

it('does not mistake a collapse-induced scroll clamp for scrolling up', () => {
    render(<TaskMessages />);
    const { element, geometry } = setGeometry(1800);
    flushLayout();
    geometry.height = 1000;
    element.scrollTop = 600;
    fireEvent.scroll(element);
    flushLayout();
    geometry.height = 1800;
    flushLayout();
    expect(element.scrollTop).toBe(1400);
});

it('waits for a hidden WebView container to regain a visible height', () => {
    render(<TaskMessages />);
    const { element, geometry } = setGeometry(1800, 0);
    flushLayout();
    expect(element.scrollTop).toBe(0);
    geometry.viewport = 400;
    flushLayout();
    expect(element.scrollTop).toBe(1400);
});

it('leaves non-task scroll containers alone', () => {
    render(<TaskMessages enabled={false} />);
    const { element } = setGeometry();
    flushLayout();
    expect(element.scrollTop).toBe(0);
});
