import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button, Checkbox, SearchInput, cn } from '@bisheng/ui'
import { Outlined } from 'bisheng-icons'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover'
import { EMPTY_ORG_SELECTION } from '@/controllers/API/log'
import type { OrgSelection } from '@/types/api/audit'
import { OrgPanelBody } from './OrgPanelBody'

interface OrgFilterProps {
  /** The page's draft selection; it takes effect when the page runs its query (AC-26). */
  value: OrgSelection
  onChange: (value: OrgSelection) => void
  /** Global super's tenant selector, when the page has one (AC-27). */
  tenantId?: number | null
  className?: string
}

const SEARCH_DELAY_MS = 300

const selectedCount = (value: OrgSelection) =>
  value.deptIds.length + Number(value.includeNone) + Number(value.includeUnrecorded)

export function OrgFilter({ value, onChange, tenantId, className }: OrgFilterProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState<OrgSelection>(value)
  const [text, setText] = useState('')
  const [keyword, setKeyword] = useState('')

  useEffect(() => {
    const timer = setTimeout(() => setKeyword(text.trim()), SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [text])

  const handleOpenChange = (next: boolean) => {
    if (next) {
      setDraft(value)
      setText('')
      setKeyword('')
    }
    setOpen(next)
  }
  const handleToggle = (id: number) => {
    const ids = draft.deptIds.includes(id) ? draft.deptIds.filter(one => one !== id) : [...draft.deptIds, id]
    setDraft({ ...draft, deptIds: ids })
  }
  const handleClear = () => {
    onChange({ ...EMPTY_ORG_SELECTION })
    setOpen(false)
  }
  const handleConfirm = () => {
    onChange(draft)
    setOpen(false)
  }

  const count = selectedCount(value)
  return (
    <Popover open={open} onOpenChange={handleOpenChange}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t('log.org.placeholder')}
          className={cn(
            'input-touch-hit relative flex h-8 w-[200px] min-w-0 cursor-pointer items-center gap-2 overflow-hidden rounded-md border border-border-base bg-bg-page px-[11px] text-left text-[length:var(--font-size-3)] font-normal leading-[var(--line-height-3)] text-text-1 outline-none transition-colors',
            'hover:border-border-deep focus-visible:border-border-deep focus-visible:shadow-focus data-[state=open]:border-border-deep data-[state=open]:shadow-focus',
            className,
          )}
        >
          <span className={cn('min-w-0 flex-1 truncate', !count && 'text-text-3')}>
            {count ? t('log.org.selected', { count }) : t('log.org.placeholder')}
          </span>
          <Outlined.Down
            aria-hidden
            className={cn('size-4 shrink-0 text-text-3 transition-transform', open && 'rotate-180')}
          />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="flex w-[360px] flex-col gap-3 p-3">
        <SearchInput
          aria-label={t('log.org.search')}
          placeholder={t('log.org.search')}
          value={text}
          onChange={event => setText(event.target.value)}
          onSearch={next => setKeyword(next.trim())}
        />
        <div className="max-h-[320px] overflow-y-auto">
          <OrgPanelBody
            tenantId={tenantId}
            keyword={keyword}
            checked={new Set(draft.deptIds)}
            onToggle={handleToggle}
            includeNone={draft.includeNone}
            includeUnrecorded={draft.includeUnrecorded}
            onIncludeNone={includeNone => setDraft({ ...draft, includeNone })}
            onIncludeUnrecorded={includeUnrecorded => setDraft({ ...draft, includeUnrecorded })}
          />
        </div>
        <div className="flex items-center justify-between gap-2 border-t pt-3">
          <Checkbox
            checked={draft.includeDescendants}
            onCheckedChange={next => setDraft({ ...draft, includeDescendants: next === true })}
            label={t('log.org.includeDescendants')}
          />
          <div className="flex gap-2">
            <Button size="small" variant="outlined" color="default" onClick={handleClear}>{t('log.org.clear')}</Button>
            <Button size="small" onClick={handleConfirm}>{t('log.org.confirm')}</Button>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  )
}
