import { Popover,PopoverContent,PopoverTrigger } from '@/components/bs-ui/popover'
import { Button,Checkbox,Tag } from '@bisheng/ui'
import { Outlined } from 'bisheng-icons'
import type { Dispatch,SetStateAction } from 'react'
import { useTranslation } from 'react-i18next'
import { FILE_STATUSES } from './KnowledgeFileStatus'

interface FileStatusFilterProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    selected: number[]
    draft: number[]
    onDraftChange: Dispatch<SetStateAction<number[]>>
    onApply: () => void
    onReset: () => void
}

export function FileStatusFilter({ open, onOpenChange, selected, draft, onDraftChange, onApply, onReset }: FileStatusFilterProps) {
    const { t } = useTranslation('knowledge')
    // A checkbox form with apply / reset, not an action menu: a popover, not a Dropdown.
    return <Popover open={open} onOpenChange={onOpenChange}>
        <PopoverTrigger asChild>
            <Button variant="ghost" size="small" iconOnly aria-label={t('status')} color={selected.length ? 'primary' : 'default'}>
                <Outlined.Filter />
            </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-auto min-w-[200px] p-2">
            <div className="flex flex-col gap-1">{[2, 1, 3, 6, 7].map(value => <Checkbox key={value} checked={draft.includes(value)}
                label={<Tag size="small" dot color={FILE_STATUSES[value].color}>{t(FILE_STATUSES[value].labelKey)}</Tag>}
                onCheckedChange={() => onDraftChange(previous => previous.includes(value)
                    ? previous.filter(item => item !== value) : [...previous, value])} />)}</div>
            <div className="mt-2 flex justify-around gap-2 border-t border-border-base pt-2">
                <Button variant="ghost" size="small" disabled={!draft.length} onClick={event => { event.stopPropagation(); onReset() }}>{t('reset')}</Button>
                <Button size="small" onClick={event => { event.stopPropagation(); onApply() }}>{t('confirm')}</Button>
            </div>
        </PopoverContent>
    </Popover>
}
