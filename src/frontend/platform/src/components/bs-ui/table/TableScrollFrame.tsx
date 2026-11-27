import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { cname } from "../utils";

export interface TableScrollShadows {
    /** Width of the fixed columns at the xl breakpoint. */
    pinnedLeft: number;
    pinnedRight: number;
}

interface TableScrollFrameProps {
    children: ReactNode;
    className?: string;
    viewportClassName: string;
    shadows: TableScrollShadows;
}

interface TableScrollShadowProps {
    side: "left" | "right";
}

function TableScrollShadow({ side }: TableScrollShadowProps) {
    return (
        <span
            aria-hidden
            data-scroll-shadow={side}
            className={cname(
                "pointer-events-none absolute top-0 bottom-[var(--table-scrollbar-height)] z-[4] w-4 overflow-hidden",
                side === "left"
                    ? "left-0 xl:left-[var(--table-shadow-left)]"
                    : "right-[var(--table-scrollbar-width)] xl:right-[var(--table-shadow-right)]",
            )}
        >
            <span className={cname(
                "absolute -inset-y-4 w-8 shadow-popup",
                side === "left" ? "-left-8" : "-right-8",
            )} />
        </span>
    );
}

export function TableScrollFrame({ children, className, viewportClassName, shadows }: TableScrollFrameProps) {
    const viewportRef = useRef<HTMLDivElement>(null);
    const [edges, setEdges] = useState({ left: false, right: false, scrollbarWidth: 0, scrollbarHeight: 0 });

    const updateEdges = useCallback(() => {
        const viewport = viewportRef.current;
        if (!viewport) return;
        const { scrollLeft, scrollWidth, clientWidth, offsetWidth, clientHeight, offsetHeight } = viewport;
        const left = scrollLeft > 1;
        const right = scrollLeft + clientWidth < scrollWidth - 1;
        const scrollbarWidth = offsetWidth - clientWidth;
        const scrollbarHeight = offsetHeight - clientHeight;
        setEdges((current) => (
            current.left === left && current.right === right
            && current.scrollbarWidth === scrollbarWidth && current.scrollbarHeight === scrollbarHeight
                ? current
                : { left, right, scrollbarWidth, scrollbarHeight }
        ));
    }, []);

    useLayoutEffect(() => {
        const viewport = viewportRef.current;
        if (!viewport) return;
        updateEdges();
        const observer = new ResizeObserver(updateEdges);
        observer.observe(viewport);
        if (viewport.firstElementChild) observer.observe(viewport.firstElementChild);
        return () => observer.disconnect();
    }, [updateEdges]);

    const offsets = {
        "--table-scrollbar-width": `${edges.scrollbarWidth}px`,
        "--table-scrollbar-height": `${edges.scrollbarHeight}px`,
        "--table-shadow-left": `${shadows.pinnedLeft ? shadows.pinnedLeft + 1 : 0}px`,
        "--table-shadow-right": `${shadows.pinnedRight + edges.scrollbarWidth}px`,
    } as CSSProperties;

    return (
        <div className={cname("relative isolate flex min-h-0 min-w-0 w-full max-w-full flex-col overflow-hidden", className)} style={offsets}>
            <div ref={viewportRef} className={cname(viewportClassName, "min-h-0")} onScroll={updateEdges}>
                {children}
            </div>
            {edges.left && <TableScrollShadow side="left" />}
            {edges.right && <TableScrollShadow side="right" />}
        </div>
    );
}
