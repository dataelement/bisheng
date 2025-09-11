import { useRef, useEffect, useCallback } from 'react'

interface UseAutoScrollOptions {
    /**
     * 自动滚动的阈值距离（像素）
     * 当滚动位置距离底部小于等于此距离时，才会自动滚动
     */
    threshold?: number
    /**
     * 滚动行为配置
     */
    scrollBehavior?: ScrollBehavior
}

export function useAutoScroll(
    scrollRef: React.RefObject<HTMLElement>,
    effect: any,
    options: UseAutoScrollOptions = {}
) {
    const {
        threshold = 250,
        scrollBehavior = 'smooth'
    } = options

    // 是否正在自动滚动（防止滚动事件干扰）
    const isAutoScrolling = useRef(false)

    // 检查是否接近底部
    const isNearBottom = useCallback(() => {
        if (!scrollRef.current) return false

        const element = scrollRef.current
        const { scrollTop, scrollHeight, clientHeight } = element
        const distanceFromBottom = scrollHeight - scrollTop - clientHeight

        return distanceFromBottom <= threshold
    }, [scrollRef, threshold])

    // 滚动到底部
    const scrollToBottom = useCallback(() => {
        if (!scrollRef.current) return

        isAutoScrolling.current = true
        const element = scrollRef.current

        element.scrollTo({
            top: element.scrollHeight,
            behavior: scrollBehavior
        })

        // 延迟重置标志，避免触发滚动事件处理
        setTimeout(() => {
            isAutoScrolling.current = false
        }, 100)
    }, [scrollRef, scrollBehavior])

    // 当依赖变化时，检查是否需要自动滚动
    useEffect(() => {
        if (effect !== undefined && !isAutoScrolling.current) {
            // 只有当前位置接近底部时才自动滚动
            if (isNearBottom()) {
                scrollToBottom()
            }
        }
    }, [effect, isNearBottom, scrollToBottom])

    return {
        isNearBottom,
        scrollToBottom
    }
}
