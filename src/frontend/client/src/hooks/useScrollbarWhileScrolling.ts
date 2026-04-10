import { useCallback, useEffect, useRef, useState } from "react";

const HIDE_DELAY_MS = 500;

/**
 * 配合全局样式 `.scroll-on-scroll`（style.css）：无滚动/未在滚动时不显示滚动条，滚动时出现，停止滚动后短暂延迟再隐藏。
 */
export function useScrollbarWhileScrolling() {
    const [scrolling, setScrolling] = useState(false);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const onScroll = useCallback(() => {
        setScrolling(true);
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => {
            setScrolling(false);
            timerRef.current = null;
        }, HIDE_DELAY_MS);
    }, []);

    useEffect(
        () => () => {
            if (timerRef.current) clearTimeout(timerRef.current);
        },
        []
    );

    return {
        onScroll,
        scrollingProps: {
            "data-scrolling": scrolling ? ("true" as const) : ("false" as const),
        },
    };
}
