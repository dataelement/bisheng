export type UsagePreset = 'today' | '30d' | 'year'
export type UsageRange = { startAt: string; endAt: string }
export const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000
export const DAY_MS = 24 * 60 * 60 * 1000
export const twoDigits = (value: number) => String(value).padStart(2, '0')

export function formatShanghaiInstant(timestamp: number): string {
    return `${new Date(timestamp + SHANGHAI_OFFSET_MS).toISOString().slice(0, 19)}+08:00`
}

export function usagePresetRange(preset: UsagePreset, now = Date.now()): UsageRange {
    const midnight = Math.floor((now + SHANGHAI_OFFSET_MS) / DAY_MS) * DAY_MS - SHANGHAI_OFFSET_MS
    const days = preset === 'today' ? 1 : preset === 'year' ? 365 : 30
    return {
        startAt: formatShanghaiInstant(midnight - (days - 1) * DAY_MS),
        endAt: formatShanghaiInstant(Math.max(now, midnight + 1000)),
    }
}

export function usageCalendarBounds(range: UsageRange) {
    const midnight = (time: number) =>
        Math.floor((time + SHANGHAI_OFFSET_MS) / DAY_MS) * DAY_MS - SHANGHAI_OFFSET_MS
    const start = midnight(Date.parse(range.startAt))
    const end = midnight(Date.parse(range.endAt) - 1) + DAY_MS
    return { start, end, days: Math.round((end - start) / DAY_MS) }
}

// Retained for the standalone design preview; product usage now stays on an exact 365-day range.
export function usageHistoryRange(endAt: string, weeks: number): UsageRange {
    const end = Date.parse(endAt)
    const midnight = Math.floor((end + SHANGHAI_OFFSET_MS) / DAY_MS) * DAY_MS - SHANGHAI_OFFSET_MS
    const weekday = (new Date(midnight + SHANGHAI_OFFSET_MS).getUTCDay() + 6) % 7
    const columns = Math.max(53, Math.min(104, Math.floor(weeks)))
    return { startAt: formatShanghaiInstant(midnight - (weekday + (columns - 1) * 7) * DAY_MS), endAt }
}

export function usageGranularity(range: UsageRange): 'hour' | 'day' {
    return usageCalendarBounds(range).days <= 31 ? 'hour' : 'day'
}

export function localInputValue(value: string): string {
    return formatShanghaiInstant(Date.parse(value)).slice(0, 16)
}

export function pointLabel(value: string, granularity: 'hour' | 'day'): string {
    const local = new Date(Date.parse(value) + SHANGHAI_OFFSET_MS)
    return granularity === 'hour'
        ? `${twoDigits(local.getUTCHours())}:00`
        : `${twoDigits(local.getUTCMonth() + 1)}-${twoDigits(local.getUTCDate())}`
}
