import type { DshUsageMetrics, DshUsageTimeSummary } from '@/types/dsh'

const DAY = 86400000
const HOUR = DAY / 24
const OFFSET = 8 * HOUR

function mixSeed(value: number): number {
    let mixed = value ^ (value >>> 16)
    mixed = Math.imul(mixed, 0x7feb352d)
    mixed ^= mixed >>> 15
    mixed = Math.imul(mixed, 0x846ca68b)
    return (mixed ^ (mixed >>> 16)) >>> 0
}

export type UsageDemoConfig = {
    origin: string
    tenantId: number
    userId: number
    userName: string
    start: string
    before: string
}

// Deployment opt-in; the regular build contains no enabled demo configuration.
export function usageDemoConfig(
    raw = import.meta.env.VITE_DSH_USAGE_DEMO,
    origin = window.location.origin,
    now = Date.now(),
): UsageDemoConfig | null {
    try {
        const config: UsageDemoConfig = JSON.parse(raw || 'null')
        if (
            !config ||
            config.origin !== origin ||
            !Number.isSafeInteger(config.tenantId) ||
            config.tenantId < 1 ||
            !Number.isSafeInteger(config.userId) ||
            config.userId < 1 ||
            typeof config.userName !== 'string' ||
            !config.userName.trim() ||
            !/^\d{4}-\d{2}-\d{2}$/.test(config.start) ||
            !/^\d{4}-\d{2}-\d{2}$/.test(config.before)
        )
            return null
        const start = Date.parse(`${config.start}T00:00:00+08:00`)
        const before = Date.parse(`${config.before}T00:00:00+08:00`)
        const today = Math.floor((now + OFFSET) / DAY) * DAY - OFFSET
        return Number.isFinite(start) &&
            Number.isFinite(before) &&
            new Date(start + OFFSET).toISOString().slice(0, 10) === config.start &&
            new Date(before + OFFSET).toISOString().slice(0, 10) === config.before &&
            start < before &&
            before <= today &&
            before - start <= 730 * DAY
            ? config
            : null
    } catch {
        return null
    }
}

const emptyMetrics = (): DshUsageMetrics => ({
    message_count: 0,
    qa_count: 0,
    failed_count: 0,
    cancelled_count: 0,
    running_count: 0,
    usage_unknown_count: 0,
    recorded_usage_count: 0,
    missing_usage_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
})

export function addDemoMetrics(real: DshUsageMetrics, demo: DshUsageMetrics): DshUsageMetrics {
    const result = emptyMetrics()
    for (const key of Object.keys(result) as Array<keyof DshUsageMetrics>) {
        result[key] = (real[key] ?? 0) + (demo[key] ?? 0)
    }
    if (result.message_count > 0 && result.recorded_usage_count === 0) {
        result.input_tokens = result.output_tokens = result.total_tokens = null
    }
    return result
}

// Deterministic hourly events keep partial ranges, daily cells and totals additive.
export function demoUsageMetrics(startAt: string, endAt: string, config: UsageDemoConfig): DshUsageMetrics {
    const start = Math.max(Date.parse(startAt), Date.parse(`${config.start}T00:00:00+08:00`))
    const end = Math.min(Date.parse(endAt), Date.parse(`${config.before}T00:00:00+08:00`))
    const result = emptyMetrics()
    for (let hour = Math.floor(start / HOUR) * HOUR; hour < end; hour += HOUR) {
        const local = hour + OFFSET
        const day = Math.floor(local / DAY)
        const hourOfDay = Math.floor(local / HOUR) % 24
        const weekday = new Date(local).getUTCDay()
        const daySeed = mixSeed(day + 7)
        const seed = mixSeed(day ^ Math.imul(hourOfDay + 1, 0x9e3779b1))
        if (
            daySeed % 5 === 0 ||
            hourOfDay < 8 ||
            hourOfDay > 20 ||
            seed % 3 !== 0 ||
            ((weekday === 0 || weekday === 6) && seed % 4 !== 0)
        )
            continue
        const dayMultiplier =
            daySeed % 127 === 0 ? 60 : daySeed % 89 === 0 ? 35 : daySeed % 53 === 0 ? 18 : daySeed % 17 === 0 ? 6 : 1
        const count = seed % 17 === 0 ? 2 : 1
        for (let event = 0; event < count; event++) {
            const timestamp = hour + (5 + event * 10) * 60000
            if (timestamp < start || timestamp >= end) continue
            const eventSeed = mixSeed(seed ^ Math.imul(event + 1, 0x45d9f3b))
            const tokens = (500_000 + (eventSeed % 6_000_001)) * dayMultiplier
            const input = Math.floor(tokens * 0.88)
            result.message_count++
            result.qa_count++
            result.recorded_usage_count++
            result.input_tokens! += input
            result.output_tokens! += tokens - input
            result.total_tokens! += tokens
        }
    }
    return result
}

export function addDemoSummary(real: DshUsageTimeSummary, config: UsageDemoConfig): DshUsageTimeSummary {
    const demo = demoUsageMetrics(real.start_at, real.end_at, config)
    if (!demo.message_count) return real
    return {
        ...real,
        demo: { before: config.before, total_tokens: demo.total_tokens! },
        totals: addDemoMetrics(real.totals, demo),
        points: real.points.map((point) => {
            const extra = demoUsageMetrics(
                new Date(Math.max(Date.parse(point.start_at), Date.parse(real.start_at))).toISOString(),
                new Date(Math.min(Date.parse(point.end_at), Date.parse(real.end_at))).toISOString(),
                config,
            )
            return extra.message_count
                ? {
                      ...point,
                      ...addDemoMetrics(point, extra),
                      demo_tokens: extra.total_tokens!,
                  }
                : point
        }),
    }
}
