export type UsageRange = { startAt: string; endAt: string }
export const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000
export const DAY_MS = 24 * 60 * 60 * 1000
export const twoDigits = (value: number) => String(value).padStart(2, '0')

export function formatShanghaiInstant(timestamp: number): string {
    return `${new Date(timestamp + SHANGHAI_OFFSET_MS).toISOString().slice(0, 19)}+08:00`
}

export function usageCalendarBounds(range: UsageRange) {
    const midnight = (time: number) =>
        Math.floor((time + SHANGHAI_OFFSET_MS) / DAY_MS) * DAY_MS - SHANGHAI_OFFSET_MS
    const start = midnight(Date.parse(range.startAt))
    const end = midnight(Date.parse(range.endAt) - 1) + DAY_MS
    return { start, end, days: Math.round((end - start) / DAY_MS) }
}

