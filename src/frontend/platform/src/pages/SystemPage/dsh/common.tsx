import { Button, Select } from '@bisheng/ui';

import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels'
import { useTranslation } from 'react-i18next'

interface ChoiceProps {
    label: string
    value: string
    options: { value: string; label: string; disabled?: boolean }[]
    onChange: (value: string) => void
    disabled?: boolean
}
export function DshChoice({
    label,
    value,
    options,
    onChange,
    disabled,
}: ChoiceProps) {
    const selectLabels = useSelectLabels()
    return (
        <Select
            {...selectLabels}
            className="w-auto min-w-40"
            options={options.filter((option) => option.value != null && option.value !== '')}
            value={value || null}
            onChange={(v) => { if (v != null) onChange(String(v)) }}
            disabled={disabled}
            placeholder={label}
            aria-label={label}
        />
    )
}
interface PagerProps {
    className?: string
    hideUnavailable?: boolean
    previous: boolean
    next: boolean
    loading?: boolean
    onPrevious: () => void
    onNext: () => void
}
export function DshPager({
    className = '',
    hideUnavailable = false,
    previous,
    next,
    loading,
    onPrevious,
    onNext,
}: PagerProps) {
    const { t } = useTranslation()
    return (
        <div className={`flex gap-2 ${className}`}>
            {(!hideUnavailable || previous) && (
                <Button variant="outlined" disabled={!previous || loading} onClick={onPrevious} color="default">
                    {t('dsh.previous')}
                </Button>
            )}
            {(!hideUnavailable || next) && (
                <Button variant="outlined" disabled={!next || loading} onClick={onNext} color="default">
                    {t('dsh.next')}
                </Button>
            )}
        </div>
    )
}
export function dshTime(value: string | null | undefined): string {
    return value ? new Date(value).toLocaleString() : '—'
}
