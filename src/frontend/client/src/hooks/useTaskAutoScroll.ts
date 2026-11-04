import { useCallback, useEffect, useRef, useState } from 'react';
import { useActivate, useUnactivate } from 'react-activation';

interface UseTaskAutoScrollOptions {
    sessionKey: string;
    enabled?: boolean;
}

const BOTTOM_THRESHOLD = 64;

/** One scroll owner per task message list, including asynchronously loaded turns. */
export function useTaskAutoScroll({ sessionKey, enabled = true }: UseTaskAutoScrollOptions) {
    // Callback refs also bind observers when a loading/empty branch is replaced
    // by the message list, without depending on the outer messages reference.
    const [container, containerRef] = useState<HTMLDivElement | null>(null);
    const [content, contentRef] = useState<HTMLDivElement | null>(null);
    const [showScrollButton, setShowScrollButton] = useState(false);
    const following = useRef(true);
    const active = useRef(true);
    const frame = useRef<number | null>(null);
    const previous = useRef({ top: 0, height: 0, viewport: 0 });

    const cancelScroll = useCallback(() => {
        if (frame.current !== null) cancelAnimationFrame(frame.current);
        frame.current = null;
    }, []);

    const scheduleScroll = useCallback(() => {
        if (!enabled || !active.current || !container || frame.current !== null) return;
        frame.current = requestAnimationFrame(() => {
            frame.current = null;
            // KeepAlive can leave the node mounted with no visible viewport.
            if (!active.current || container.clientHeight === 0) return;
            if (following.current) {
                container.scrollTo({ top: container.scrollHeight, behavior: 'auto' });
                previous.current = {
                    top: container.scrollTop,
                    height: container.scrollHeight,
                    viewport: container.clientHeight,
                };
            }
            setShowScrollButton(
                container.scrollHeight - container.scrollTop - container.clientHeight > BOTTOM_THRESHOLD,
            );
        });
    }, [container, enabled]);

    const scrollToBottom = useCallback(() => {
        following.current = true;
        setShowScrollButton(false);
        scheduleScroll();
    }, [scheduleScroll]);

    useEffect(() => {
        if (!enabled || !container || !content) return;

        const rememberPosition = () => {
            previous.current = {
                top: container.scrollTop,
                height: container.scrollHeight,
                viewport: container.clientHeight,
            };
        };
        rememberPosition();

        const release = () => {
            following.current = false;
            cancelScroll();
        };
        const handleScroll = () => {
            if (!active.current || container.clientHeight === 0) return;
            const last = previous.current;
            const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight <= BOTTOM_THRESHOLD;
            // A shrinking body or a growing viewport can clamp scrollTop to its
            // new maximum. Other upward movement is reader intent, even when
            // output grows concurrently with dragging the scrollbar.
            const layoutChanged = container.scrollHeight !== last.height || container.clientHeight !== last.viewport;
            const maxTop = Math.max(0, container.scrollHeight - container.clientHeight);
            const clampedByLayout = layoutChanged && maxTop < last.top && container.scrollTop >= maxTop - 1;
            if (container.scrollTop < last.top - 1 && !clampedByLayout) {
                release();
            } else if (container.scrollTop > last.top && nearBottom) {
                following.current = true;
            }
            rememberPosition();
            setShowScrollButton(!nearBottom);
        };
        const handleWheel = (event: WheelEvent) => {
            if (event.deltaY < 0) release();
        };
        let touchY: number | undefined;
        const handleTouchStart = (event: TouchEvent) => {
            touchY = event.touches[0]?.clientY;
        };
        const handleTouchMove = (event: TouchEvent) => {
            const nextY = event.touches[0]?.clientY;
            if (nextY !== undefined && touchY !== undefined && nextY > touchY) release();
            touchY = nextY;
        };
        const handleKeyDown = (event: KeyboardEvent) => {
            const target = event.target;
            if (target instanceof HTMLElement && target.closest('input, textarea, [contenteditable="true"]')) return;
            if (['ArrowUp', 'PageUp', 'Home'].includes(event.key) || (event.key === ' ' && event.shiftKey)) release();
        };

        container.addEventListener('scroll', handleScroll, { passive: true });
        container.addEventListener('wheel', handleWheel, { passive: true });
        container.addEventListener('touchstart', handleTouchStart, { passive: true });
        container.addEventListener('touchmove', handleTouchMove, { passive: true });
        container.addEventListener('keydown', handleKeyDown);
        // Watch the growing content, not just React's outer message array.
        // This includes child hydration, Markdown/images and fold animations.
        const observer = new ResizeObserver(scheduleScroll);
        observer.observe(content);
        observer.observe(container);
        return () => {
            observer.disconnect();
            cancelScroll();
            container.removeEventListener('scroll', handleScroll);
            container.removeEventListener('wheel', handleWheel);
            container.removeEventListener('touchstart', handleTouchStart);
            container.removeEventListener('touchmove', handleTouchMove);
            container.removeEventListener('keydown', handleKeyDown);
        };
    }, [container, content, enabled, cancelScroll, scheduleScroll]);

    // Each session entry starts at its latest output; subsequent layout changes
    // follow it until the reader explicitly scrolls upward.
    useEffect(() => {
        if (enabled && container && content) scrollToBottom();
    }, [sessionKey, container, content, enabled, scrollToBottom]);

    useActivate(() => {
        active.current = true;
        if (enabled) scrollToBottom();
    });
    useUnactivate(() => {
        active.current = false;
        cancelScroll();
    });

    return { containerRef, contentRef, showScrollButton, scrollToBottom };
}
