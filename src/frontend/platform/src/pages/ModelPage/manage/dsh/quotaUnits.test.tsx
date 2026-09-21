import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'
import { QuotaInput } from './QuotaInput'
import { formatWanQuota, tokensToWan, wanToTokenDraft } from './quotaUnits'
import { validUserDraft } from './useUserPolicyDrafts'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

it.each([0, 1, 6000, 10000, 100000, 1000000, 123456789, Number.MAX_SAFE_INTEGER])(
    'round trips %i Tokens with integer precision',
    (tokens) => {
        expect(Number(wanToTokenDraft(tokensToWan(tokens)))).toBe(tokens)
    },
)

it.each(['-1', '1e3', 'abc', '.', '0.00001', '1.00000', '900719925474.0992'])(
    'keeps invalid wan amount %s out of a saveable draft',
    (text) => {
        expect(validUserDraft({ enabled: false, limit: wanToTokenDraft(text) })).toBe(false)
    },
)

it('formats short and large quotas without rounding away Tokens', () => {
    expect(tokensToWan('')).toBe('')
    expect(wanToTokenDraft('')).toBe('')
    expect(wanToTokenDraft('.6')).toBe('6000')
    expect(wanToTokenDraft('0.0001')).toBe('1')
    expect(formatWanQuota(10000000)).toBe('1,000')
    expect(formatWanQuota(Number.MAX_SAFE_INTEGER)).toBe('900,719,925,474.0991')
})

function Editor() {
    const [value, setValue] = useState('0')
    return (
        <>
            <QuotaInput label="Quota" disabled={false} value={value} onChange={setValue} />
            <output data-testid="tokens">{value}</output>
        </>
    )
}

it('keeps a decimal point while typing and clears to zero on blur', () => {
    render(<Editor />)
    const input = screen.getByLabelText('Quota')
    fireEvent.change(input, { target: { value: '0.' } })
    expect(input).toHaveValue('0.')
    fireEvent.change(input, { target: { value: '0.6' } })
    expect(input).toHaveValue('0.6')
    expect(screen.getByTestId('tokens')).toHaveTextContent('6000')
    fireEvent.change(input, { target: { value: '' } })
    expect(input).toHaveAttribute('aria-invalid', 'false')
    fireEvent.blur(input)
    expect(input).toHaveValue('0')
    expect(screen.getByTestId('tokens')).toBeEmptyDOMElement()
})

it('updates the displayed unit value when a shared user draft changes', () => {
    const { rerender } = render(<QuotaInput label="Quota" disabled={false} value="6000" onChange={vi.fn()} />)
    expect(screen.getByLabelText('Quota')).toHaveValue('0.6')
    rerender(<QuotaInput label="Quota" disabled={false} value="100000" onChange={vi.fn()} />)
    expect(screen.getByLabelText('Quota')).toHaveValue('10')
})
