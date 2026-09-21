import { describe, expect, it } from 'vitest'
import {
    relativeUsageHeatLevel,
    USAGE_HEAT_COLORS,
    USAGE_HEAT_MAX,
    usageHeatLevel,
} from './usageHeatScale'

describe('fixed equal-interval Token heat scale', () => {
    it('uses five positive levels and a separate neutral zero fill', () => {
        expect(USAGE_HEAT_COLORS).toHaveLength(6)
        expect(new Set(USAGE_HEAT_COLORS).size).toBe(6)
        expect(usageHeatLevel(1, 'day')).toBe(1)
        expect(usageHeatLevel(0, 'day')).toBe(0)
    })
    it.each(['day', 'hour'] as const)('assigns exact %s thresholds to the higher band', (unit) => {
        const step = USAGE_HEAT_MAX[unit] / 5
        Array.from({ length: 4 }, (_, index) => index + 1).forEach((index) => {
            const threshold = step * index
            expect(usageHeatLevel(threshold - 1, unit)).toBe(index)
            expect(usageHeatLevel(threshold, unit)).toBe(index + 1)
        })
    })
    it.each([
        ['day', 240_000_000],
        ['hour', 24_000_000],
    ] as const)('uses five equal %s bands of %i Tokens', (unit, step) => {
        expect(USAGE_HEAT_MAX[unit]).toBe(step * 5)
        expect(Array.from({ length: 5 }, (_, index) => usageHeatLevel(step * (index + 0.5), unit))).toEqual([
            1, 2, 3, 4, 5,
        ])
        expect(usageHeatLevel(USAGE_HEAT_MAX[unit], unit)).toBe(5)
        expect(usageHeatLevel(USAGE_HEAT_MAX[unit] * 10, unit)).toBe(5)
    })
    it('maps daily usage proportionally over the fixed zero to 1.2 billion domain', () => {
        expect(
            [20_000_000, 50_000_000, 100_000_000, 300_000_000, 1_000_000_000, 1_200_000_000].map((tokens) =>
                usageHeatLevel(tokens, 'day'),
            ),
        ).toEqual([1, 1, 1, 2, 5, 5])
    })
    it('condenses the palette to five fills while preserving the softened peak', () => {
        expect(
            [100_000_000, 200_000_000, 400_000_000, 600_000_000].map((tokens) =>
                usageHeatLevel(tokens, 'day'),
            ),
        ).toEqual([1, 1, 2, 3])
        expect(USAGE_HEAT_COLORS.slice(1)).toEqual([
            'bg-primary/15',
            'bg-primary/35',
            'bg-primary/50',
            'bg-primary/75',
            'bg-primary bg-gradient-to-b from-foreground/20 to-foreground/20',
        ])
    })
    it('keeps small amounts visible and saturates large outliers without rescaling', () => {
        expect([200_000, 20_000_000, 70_000_000].map((tokens) => usageHeatLevel(tokens, 'day'))).toEqual([
            1, 1, 1,
        ])
        expect(usageHeatLevel(Number.MAX_SAFE_INTEGER, 'day')).toBe(5)
        expect(usageHeatLevel(20_000_000, 'day')).toBe(1)
    })
    it('uses hourly thresholds for hourly tiles', () => {
        expect(usageHeatLevel(60_000_000, 'hour')).toBe(3)
        expect(usageHeatLevel(60_000_000, 'day')).toBe(1)
    })
    it.each([null, -1, NaN, Infinity])(
        'keeps invalid or unknown usage out of the positive palette: %s',
        (tokens) => {
            expect(usageHeatLevel(tokens, 'day')).toBe(0)
        },
    )
})

describe('relative message heat scale', () => {
    it('keeps zero neutral and spreads positive counts across the shared five-level palette', () => {
        expect(relativeUsageHeatLevel(0, 100)).toBe(0)
        expect([1, 20, 21, 60, 100].map((messages) => relativeUsageHeatLevel(messages, 100))).toEqual([
            1, 1, 2, 3, 5,
        ])
    })

    it.each([null, -1, NaN, Infinity])('keeps invalid message counts neutral: %s', (messages) => {
        expect(relativeUsageHeatLevel(messages, 100)).toBe(0)
    })

    it('keeps message counts neutral when the visible range has no positive maximum', () => {
        expect(relativeUsageHeatLevel(1, 0)).toBe(0)
    })
})
