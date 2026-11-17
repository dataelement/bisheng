import { useLayoutEffect, useState, type RefObject } from 'react';
import { getScrollParent } from './markdownOutlineUtils';

/** Rebuild the document after its animated scrollport has a settled layout. */
export function usePreviewLayout(rootRef: RefObject<HTMLElement>) {
    const [revision, setRevision] = useState(0);

    useLayoutEffect(() => {
        const root = rootRef.current;
        if (!root) return undefined;
        const scroller = getScrollParent(root) ?? root.parentElement;
        if (!scroller) return undefined;

        let timer = 0;
        let frame = 0;
        let width = -1;
        let height = -1;
        const cancel = () => {
            window.clearTimeout(timer);
            window.cancelAnimationFrame(frame);
        };
        const schedule = (force = false) => {
            const nextWidth = scroller.clientWidth;
            const nextHeight = scroller.clientHeight;
            if (nextWidth <= 0 || nextHeight <= 0) {
                cancel();
                width = height = -1;
                return;
            }
            if (!force && width === nextWidth && height === nextHeight) return;
            cancel();
            // ResizeObserver fires throughout the drawer/fullscreen animation.
            // Parse once after it settles instead of reparsing on every frame.
            timer = window.setTimeout(() => {
                frame = window.requestAnimationFrame(() => {
                    if (scroller.clientWidth <= 0 || scroller.clientHeight <= 0) return;
                    width = scroller.clientWidth;
                    height = scroller.clientHeight;
                    setRevision((value) => value + 1);
                });
            }, 120);
        };
        const onResize = () => schedule();
        const onVisibility = () => {
            if (document.visibilityState === 'visible') schedule(true);
        };
        // A late webfont can change line wrapping without changing the
        // scrollport dimensions. Give embedded engines a fresh text layout too.
        const onFontsLoaded = () => schedule(true);
        const onTransitionEnd = (event: TransitionEvent) => {
            // Opacity/transform animations can finish without a size change.
            // Ignore transitions inside the document (buttons, tooltips, etc.).
            if (event.target instanceof HTMLElement && event.target.contains(root)) schedule(true);
        };
        const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(onResize);
        observer?.observe(scroller);
        window.addEventListener('resize', onResize);
        document.addEventListener('visibilitychange', onVisibility);
        document.fonts?.addEventListener('loadingdone', onFontsLoaded);
        document.addEventListener('transitionend', onTransitionEnd, true);
        schedule();

        return () => {
            cancel();
            observer?.disconnect();
            window.removeEventListener('resize', onResize);
            document.removeEventListener('visibilitychange', onVisibility);
            document.fonts?.removeEventListener('loadingdone', onFontsLoaded);
            document.removeEventListener('transitionend', onTransitionEnd, true);
        };
    }, [rootRef]);

    return revision;
}
