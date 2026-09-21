// Shift decimal digits as strings so every integer Token survives the round trip.
export function tokensToWan(value: string | number): string {
    const raw = String(value)
    if (!/^\d+$/.test(raw)) return raw
    const digits = raw.replace(/^0+(?=\d)/, '').padStart(5, '0')
    const whole = digits.slice(0, -4).replace(/^0+(?=\d)/, '')
    const fraction = digits.slice(-4).replace(/0+$/, '')
    return fraction ? `${whole}.${fraction}` : whole
}

export function wanToTokenDraft(value: string): string {
    if (value === '') return ''
    // Invalid text remains invalid in the integer-token draft and blocks Save.
    if (!/^(?:\d+(?:\.\d{0,4})?|\.\d{1,4})$/.test(value)) return value
    const [whole, fraction = ''] = value.split('.')
    return `${whole || '0'}${fraction.padEnd(4, '0')}`.replace(/^0+(?=\d)/, '')
}

export function formatWanQuota(tokens: number): string {
    const [whole, fraction] = tokensToWan(tokens).split('.')
    const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    return fraction ? `${grouped}.${fraction}` : grouped
}
