import { describe, expect, it } from 'vitest'
import { formatUsageTokens } from './usageTokenFormat'
import fixtures from './usageTokenFormat.fixtures.json'

describe('localized Token amounts', () => {
    it.each(fixtures)('formats $value in $locale with an exact count', ({ value, locale, compact, exact }) => {
        expect(formatUsageTokens(value, locale)).toEqual({ compact, exact })
    })
})
