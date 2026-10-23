import { useEffect, useRef, useState } from 'react'

export const USAGE_TILE_SIZE = 12
export const USAGE_TILE_GAP = 3
// Reserve the card padding and border while allowing the calendar to start at the left edge.
export const USAGE_CHART_GUTTER = 36

export function usageCalendarWeeks(width: number): number {
    return Math.max(
        53,
        Math.min(
            104,
            Math.floor((width - USAGE_CHART_GUTTER + USAGE_TILE_GAP) / (USAGE_TILE_SIZE + USAGE_TILE_GAP)),
        ),
    )
}

export function useUsageCalendarWidth() {
    const ref = useRef<HTMLElement>(null)
    const [weeks, setWeeks] = useState(53)
    useEffect(() => {
        const element = ref.current
        if (!element) return
        let timer: ReturnType<typeof setTimeout>
        const update = (width: number) => {
            clearTimeout(timer)
            timer = setTimeout(() => setWeeks(usageCalendarWeeks(width)), 150)
        }
        update(element.getBoundingClientRect().width)
        const observer = new ResizeObserver(([entry]) => update(entry.contentRect.width))
        observer.observe(element)
        return () => {
            clearTimeout(timer)
            observer.disconnect()
        }
    }, [])
    return { calendarRef: ref, weeks }
}
