import { useRef, useEffect, useCallback } from 'react'

interface UseAutoScrollOptions {
    /**
     * Distance from the bottom (in pixels) within which auto-scroll stays active.
     * When the scroll position is within this distance from the bottom, the view
     * keeps following new content.
     */
    threshold?: number
    /**
     * Scroll behavior. Defaults to 'smooth' for the legacy chat experience.
     * High-frequency streaming surfaces (e.g. Linsight) should pass 'auto' to
     * avoid per-frame jitter from queued smooth animations.
     */
    scrollBehavior?: ScrollBehavior
    /**
     * Opt-in stickiness model. When enabled, the hook tracks whether the user is
     * "stuck" to the bottom: any manual scroll-up past the threshold detaches
     * auto-scroll, and it only re-attaches once the user scrolls back to the
     * bottom. Defaults to false to preserve the legacy per-effect behavior where
     * stickiness is re-evaluated on every dependency change.
     */
    releaseOnScrollUp?: boolean
}

export function useAutoScroll(
    scrollRef: React.RefObject<HTMLElement>,
    effect: any,
    options: UseAutoScrollOptions = {}
) {
    const {
        threshold = 250,
        scrollBehavior = 'smooth',
        releaseOnScrollUp = false
    } = options

    // Whether an auto-scroll is in progress (prevents the scroll listener from
    // mistaking our own programmatic scroll for a user gesture).
    const isAutoScrolling = useRef(false)

    // Stickiness state for releaseOnScrollUp mode: when true the view follows new
    // content; a manual scroll-up detaches it until the user returns to bottom.
    const isStuckToBottom = useRef(true)

    // Check whether the view is near the bottom.
    const isNearBottom = useCallback(() => {
        if (!scrollRef.current) return false

        const element = scrollRef.current
        const { scrollTop, scrollHeight, clientHeight } = element
        const distanceFromBottom = scrollHeight - scrollTop - clientHeight

        return distanceFromBottom <= threshold
    }, [scrollRef, threshold])

    // Scroll to the bottom.
    const scrollToBottom = useCallback(() => {
        if (!scrollRef.current) return

        isAutoScrolling.current = true
        // A programmatic jump to bottom re-attaches the sticky follow.
        isStuckToBottom.current = true
        const element = scrollRef.current

        element.scrollTo({
            top: element.scrollHeight,
            behavior: scrollBehavior
        })

        // Reset the flag after the scroll settles so the listener can resume
        // observing genuine user gestures.
        setTimeout(() => {
            isAutoScrolling.current = false
        }, 100)
    }, [scrollRef, scrollBehavior])

    // releaseOnScrollUp: detach auto-scroll the moment the user scrolls up past
    // the threshold, and re-attach once they scroll back to the bottom.
    useEffect(() => {
        if (!releaseOnScrollUp) return
        const element = scrollRef.current
        if (!element) return

        const handleScroll = () => {
            // Ignore scroll events emitted by our own programmatic scrolling.
            if (isAutoScrolling.current) return
            isStuckToBottom.current = isNearBottom()
        }

        element.addEventListener('scroll', handleScroll, { passive: true })
        return () => element.removeEventListener('scroll', handleScroll)
    }, [scrollRef, releaseOnScrollUp, isNearBottom])

    // When the dependency changes, follow new content if appropriate.
    useEffect(() => {
        if (effect === undefined || isAutoScrolling.current) return

        if (releaseOnScrollUp) {
            // Sticky model: only follow while attached to the bottom.
            if (isStuckToBottom.current) {
                scrollToBottom()
            }
        } else if (isNearBottom()) {
            // Legacy model: re-evaluate proximity on every change.
            scrollToBottom()
        }
    }, [effect, isNearBottom, scrollToBottom, releaseOnScrollUp])

    return {
        isNearBottom,
        scrollToBottom
    }
}
