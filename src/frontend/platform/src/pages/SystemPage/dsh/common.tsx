import { Button } from '@/components/bs-ui/button'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/bs-ui/select'
import { useTranslation } from 'react-i18next'

interface ChoiceProps {
    label: string
    value: string
    options: { value: string; label: string }[]
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
    return (
        <Select value={value} onValueChange={onChange} disabled={disabled}>
            <SelectTrigger aria-label={label} className="w-auto min-w-40">
                <SelectValue placeholder={label} />
            </SelectTrigger>
            <SelectContent>
                {options.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                        {option.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}
interface PagerProps {
    previous: boolean
    next: boolean
    loading?: boolean
    onPrevious: () => void
    onNext: () => void
}
export function DshPager({
    previous,
    next,
    loading,
    onPrevious,
    onNext,
}: PagerProps) {
    const { t } = useTranslation()
    return (
        <div className="flex gap-2">
            <Button
                variant="outline"
                disabled={!previous || loading}
                onClick={onPrevious}
            >
                {t('dsh.previous')}
            </Button>
            <Button
                variant="outline"
                disabled={!next || loading}
                onClick={onNext}
            >
                {t('dsh.next')}
            </Button>
        </div>
    )
}
export function dshTime(value: string | null | undefined): string {
    return value ? new Date(value).toLocaleString() : '—'
}
