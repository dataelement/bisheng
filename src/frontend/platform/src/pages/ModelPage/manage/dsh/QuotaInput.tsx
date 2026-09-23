import { Input } from '@/components/bs-ui/input'
import { useEffect, useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { tokensToWan, wanToTokenDraft } from './quotaUnits'
import { validUserDraft } from './useUserPolicyDrafts'

interface QuotaInputProps {
    value: string
    label: string
    disabled: boolean
    onChange: (tokens: string) => void
}

export function QuotaInput({ value, label, disabled, onChange }: QuotaInputProps) {
    const { t } = useTranslation()
    const errorId = useId()
    const [text, setText] = useState(() => tokensToWan(value))
    useEffect(() => {
        setText((current) => (wanToTokenDraft(current) === value ? current : tokensToWan(value)))
    }, [value])
    const valid = validUserDraft({ enabled: false, limit: value })
    return (
        <div>
            <Input
                aria-label={label}
                aria-invalid={!valid}
                aria-describedby={valid ? undefined : errorId}
                inputMode="decimal"
                className="tabular-nums text-base md:text-sm"
                value={text}
                disabled={disabled}
                onChange={(event) => {
                    setText(event.target.value)
                    onChange(wanToTokenDraft(event.target.value))
                }}
                onBlur={() => {
                    if (valid) setText(tokensToWan(value || '0'))
                }}
            />
            {!valid && (
                <p id={errorId} className="mt-1 text-xs text-destructive">
                    {t('dsh.invalidWanQuota')}
                </p>
            )}
        </div>
    )
}
