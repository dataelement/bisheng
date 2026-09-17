import zh from '../../../../public/locales/zh-Hans/bs.json'

export function formatUsageTokens(value: number, locale: string) {
    const exact = new Intl.NumberFormat(locale, {
        maximumFractionDigits: 0,
    }).format(value)
    const isChinese = /^zh(-|$)/i.test(locale)
    if (isChinese) {
        const levels = [
            {
                threshold: 1_000_000_000_000,
                divisor: 1_000_000_000_000,
                unit: zh.dsh.tokenUnits.trillion,
            },
            {
                threshold: 100_000_000_000,
                divisor: 100_000_000_000,
                unit: zh.dsh.tokenUnits.hundredBillion,
                maximum: 9.99,
            },
            {
                threshold: 100_000_000,
                divisor: 100_000_000,
                unit: zh.dsh.tokenUnits.hundredMillion,
                maximum: 999.99,
            },
            {
                threshold: 10_000,
                divisor: 10_000,
                unit: zh.dsh.tokenUnits.tenThousand,
                maximum: 9_999.99,
            },
        ]
        const level = levels.find(({ threshold }) => value >= threshold)
        if (!level) return { compact: exact, exact }
        const scaled = Math.min(
            value / level.divisor,
            level.maximum ?? Number.POSITIVE_INFINITY,
        )
        const number = new Intl.NumberFormat(locale, {
            maximumFractionDigits: 2,
        }).format(scaled)
        return { compact: `${number}${level.unit}`, exact }
    }
    const compact =
        value < 1_000
            ? exact
            : new Intl.NumberFormat(locale, {
                  notation: 'compact',
                  maximumFractionDigits: 2,
              }).format(value)
    return { compact, exact }
}
