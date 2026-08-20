import { useEffect, useRef, type RefObject } from "react"

interface UseAutoScrollToNewComponentProps {
    componentIds: string[]
    dashboardId?: string
    enabled: boolean
    scrollContainerRef: RefObject<HTMLDivElement>
}

type ComponentLayoutRect = Pick<DOMRect, "top" | "left" | "width" | "height">

const MAX_LAYOUT_WAIT_FRAMES = 30

const getComponentLayoutRect = (component: HTMLElement): ComponentLayoutRect => {
    const { top, left, width, height } = component.getBoundingClientRect()
    return { top, left, width, height }
}

const isStableLayout = (
    previousRect: ComponentLayoutRect | undefined,
    currentRect: ComponentLayoutRect,
) => {
    if (!previousRect || currentRect.width <= 0 || currentRect.height <= 0) return false

    return Object.keys(currentRect).every(key => (
        Math.abs(
            currentRect[key as keyof ComponentLayoutRect]
            - previousRect[key as keyof ComponentLayoutRect],
        ) < 0.5
    ))
}

export const useAutoScrollToNewComponent = ({
    componentIds,
    dashboardId,
    enabled,
    scrollContainerRef,
}: UseAutoScrollToNewComponentProps) => {
    const previousDashboardIdRef = useRef<string>()
    const previousComponentIdsRef = useRef<Set<string>>(new Set())

    useEffect(() => {
        const currentComponentIds = new Set(componentIds)

        if (previousDashboardIdRef.current !== dashboardId) {
            previousDashboardIdRef.current = dashboardId
            previousComponentIdsRef.current = currentComponentIds
            return
        }

        const addedComponentId = componentIds.find(
            componentId => !previousComponentIdsRef.current.has(componentId),
        )
        previousComponentIdsRef.current = currentComponentIds

        if (!enabled || !addedComponentId) return

        let animationFrame: number
        let frameCount = 0
        let previousRect: ComponentLayoutRect | undefined

        const scrollWhenLayoutIsStable = () => {
            animationFrame = requestAnimationFrame(() => {
                frameCount += 1
                const container = scrollContainerRef.current
                if (!container) return

                const component = Array.from(
                    container.querySelectorAll<HTMLElement>("[data-dashboard-component-id]"),
                ).find(element => element.dataset.dashboardComponentId === addedComponentId)
                if (!component) {
                    if (frameCount < MAX_LAYOUT_WAIT_FRAMES) scrollWhenLayoutIsStable()
                    return
                }

                const currentRect = getComponentLayoutRect(component)
                const layoutIsReady = currentRect.width > 0 && currentRect.height > 0
                if (layoutIsReady && (
                    isStableLayout(previousRect, currentRect)
                    || frameCount >= MAX_LAYOUT_WAIT_FRAMES
                )) {
                    component.scrollIntoView({
                        behavior: "smooth",
                        block: "center",
                        inline: "center",
                    })
                    return
                }

                previousRect = currentRect
                if (frameCount < MAX_LAYOUT_WAIT_FRAMES) scrollWhenLayoutIsStable()
            })
        }

        scrollWhenLayoutIsStable()

        return () => cancelAnimationFrame(animationFrame)
    }, [componentIds, dashboardId, enabled, scrollContainerRef])
}
