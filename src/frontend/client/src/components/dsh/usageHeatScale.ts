// Fixed domains give equally spaced bands the same meaning across users and date ranges.
export const USAGE_HEAT_MAX = {
    day: 1_200_000_000,
    hour: 120_000_000,
} as const

export const MESSAGE_HEAT_MAX = {
    day: 36,
    hour: 12,
} as const

export const USAGE_HEAT_COLORS = [
    'bg-fill-2',
    'bg-blue-600/15',
    'bg-blue-600/35',
    'bg-blue-600/50',
    'bg-blue-600/75',
    // Extend the peak toward the theme foreground: darker in light mode, lighter in dark mode.
    'bg-blue-600 bg-gradient-to-b from-black/20 to-black/20 dark:from-white/20 dark:to-white/20',
] as const

export function usageHeatLevel(tokens: number | null, unit: 'hour' | 'day'): number {
    if (tokens === null || !Number.isFinite(tokens) || tokens <= 0) return 0
    const levels = USAGE_HEAT_COLORS.length - 1
    const step = USAGE_HEAT_MAX[unit] / levels
    return Math.min(levels, 1 + Math.floor(tokens / step))
}

export function messageHeatLevel(value: number | null, unit: 'hour' | 'day'): number {
    if (value === null || !Number.isFinite(value) || value <= 0) return 0
    const levels = USAGE_HEAT_COLORS.length - 1
    const step = MESSAGE_HEAT_MAX[unit] / levels
    return Math.min(levels, 1 + Math.floor(value / step))
}

export function relativeUsageHeatLevel(value: number | null, maximum: number): number {
    if (value === null || !Number.isFinite(value) || value <= 0 || maximum <= 0) return 0
    const levels = USAGE_HEAT_COLORS.length - 1
    return Math.min(levels, Math.ceil((value / maximum) * levels))
}
