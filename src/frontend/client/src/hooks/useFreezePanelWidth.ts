import { useCallback, useLayoutEffect, useRef, useState } from 'react';

/**
 * Freeze a popup panel's content-fit width once its first batch of data has
 * rendered, so pagination / search filtering / longer late-arriving items
 * cannot change the panel width while it stays open.
 *
 * Usage: the panel (or its popup) carries `min-w-* max-w-*` classes and no
 * fixed width, so it auto-fits its content. Pass `ready = true` once the
 * first data batch is rendered (e.g. react-query `isFetched`); the hook then
 * measures the element once and returns an inline `width` that pins it.
 *
 * `open` is only needed when the hook lives in a component that stays mounted
 * across open/close (it resets the frozen width on close). When the host
 * component itself mounts/unmounts with the Radix popup content, omit it.
 */
export function useFreezePanelWidth(ready: boolean, open = true) {
    const nodeRef = useRef<HTMLElement | null>(null);
    const [width, setWidth] = useState<number | undefined>(undefined);

    const ref = useCallback((node: HTMLElement | null) => {
        nodeRef.current = node;
    }, []);

    useLayoutEffect(() => {
        if (!open) setWidth(undefined);
    }, [open]);

    useLayoutEffect(() => {
        if (!open || !ready || width !== undefined) return;
        const el = nodeRef.current;
        if (!el) return;
        // offsetWidth ignores the Radix zoom-in entry transform (unlike
        // getBoundingClientRect) but rounds down; +1px keeps the widest row
        // from picking up a truncation ellipsis it didn't have when measured.
        setWidth(el.offsetWidth + 1);
    }, [open, ready, width]);

    return { ref, style: width !== undefined ? ({ width } as const) : undefined };
}
