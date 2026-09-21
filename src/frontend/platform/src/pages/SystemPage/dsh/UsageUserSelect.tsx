import { Button } from '@/components/bs-ui/button'
import { Command, CommandInput, CommandItem, CommandList } from '@/components/bs-ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/bs-ui/popover'
import { getDshUsagePresentationOverview as getDshUsageOverview } from '@/controllers/API/dshUsagePresentation'
import type { DshUsageOverviewPage, DshUsageOverviewUser } from '@/types/dsh'
import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { UsageRange } from './usageRange'

interface UsageUserSelectProps {
    value: DshUsageOverviewUser | null
    range: UsageRange
    onChange: (user: DshUsageOverviewUser) => void
}

export function UsageUserSelect({ value, range, onChange }: UsageUserSelectProps) {
    const { t } = useTranslation()
    const [open, setOpen] = useState(false)
    const [keyword, setKeyword] = useState('')
    const [cursor, setCursor] = useState<string>()
    const [page, setPage] = useState<DshUsageOverviewPage | null>(null)
    const [error, setError] = useState(false)
    const [loading, setLoading] = useState(false)
    const [revision, setRevision] = useState(0)
    useEffect(() => {
        if (!open) return
        const abort = new AbortController()
        if (!cursor) setPage(null)
        setError(false)
        setLoading(true)
        const timer = window.setTimeout(
            () => {
                getDshUsageOverview(
                    { ...range, keyword: keyword.trim() || undefined, cursor, limit: 20 },
                    abort.signal,
                )
                    .then((result) => {
                        if (!abort.signal.aborted) {
                            setPage((previous) =>
                                cursor && previous
                                    ? {
                                          ...result,
                                          items: [
                                              ...new Map(
                                                  [...previous.items, ...result.items].map((user) => [
                                                      user.user_id,
                                                      user,
                                                  ]),
                                              ).values(),
                                          ],
                                      }
                                    : result,
                            )
                        }
                    })
                    .catch(() => {
                        if (!abort.signal.aborted) setError(true)
                    })
                    .finally(() => {
                        if (!abort.signal.aborted) setLoading(false)
                    })
            },
            keyword.trim() ? 250 : 0,
        )
        return () => {
            window.clearTimeout(timer)
            abort.abort()
        }
    }, [open, keyword, cursor, range, revision])
    const handleLoadMore = () => {
        if (loading || error || !page?.has_more || !page.next_cursor) return
        setLoading(true)
        setCursor(page.next_cursor)
    }
    return (
        <Popover
            open={open}
            onOpenChange={(next) => {
                setOpen(next)
                setKeyword('')
                setCursor(undefined)
                setPage(null)
                setError(false)
                setLoading(next)
            }}
            modal={false}
        >
            <PopoverTrigger asChild>
                <Button
                    variant="outline"
                    className="h-9 w-72 max-w-full justify-between font-normal"
                    aria-label={t('dsh.selectUsageUser')}
                    aria-expanded={open}
                >
                    <span className="truncate">{value?.user_name ?? t('dsh.selectUsageUser')}</span>
                    <ChevronDown className="ml-2 size-4 shrink-0 opacity-60" />
                </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-80 max-w-[calc(100vw-2rem)] p-0">
                <Command shouldFilter={false} label={t('dsh.userSearchResults')}>
                    <CommandInput
                        value={keyword}
                        maxLength={128}
                        placeholder={t('dsh.searchUsers')}
                        aria-label={t('dsh.searchUsers')}
                        onValueChange={(next) => {
                            setKeyword(next)
                            setCursor(undefined)
                            setPage(null)
                            setError(false)
                            setLoading(true)
                        }}
                    />
                    <CommandList
                        aria-label={t('dsh.userSearchResults')}
                        aria-busy={loading}
                        className="h-60 max-h-60 overflow-y-auto"
                        onScroll={(event) => {
                            const { scrollHeight, scrollTop, clientHeight } = event.currentTarget
                            if (scrollHeight - scrollTop - clientHeight < 24) handleLoadMore()
                        }}
                    >
                        {(error || (!page?.items.length && !loading)) && (
                            <p
                                role={error ? 'alert' : 'status'}
                                className="p-4 text-sm text-muted-foreground"
                            >
                                {t(error ? 'dsh.unavailable' : 'dsh.empty')}
                            </p>
                        )}
                        {page?.items.map((user) => (
                            <CommandItem
                                key={user.user_id}
                                value={String(user.user_id)}
                                onSelect={() => {
                                    onChange(user)
                                    setOpen(false)
                                }}
                                className="min-h-12 gap-2"
                                data-selected-user={value?.user_id === user.user_id}
                            >
                                <span className="flex min-w-0 flex-1 flex-col items-start gap-1">
                                    <span className="w-full truncate">{user.user_name}</span>
                                    <span className="w-full truncate text-xs text-muted-foreground">
                                        {user.department_name || '—'}
                                    </span>
                                </span>
                                {value?.user_id === user.user_id && (
                                    <Check className="size-4 shrink-0" aria-hidden="true" />
                                )}
                            </CommandItem>
                        ))}
                        {loading && (
                            <p role="status" className="p-4 text-sm text-muted-foreground">
                                {t('dsh.loading')}
                            </p>
                        )}
                        {error && (
                            <CommandItem value="retry" onSelect={() => setRevision((value) => value + 1)}>
                                {t('dsh.refresh')}
                            </CommandItem>
                        )}
                        {page?.has_more && !loading && !error && (
                            <CommandItem value="next-page" onSelect={handleLoadMore}>
                                {t('dsh.loadMoreUsers')}
                            </CommandItem>
                        )}
                    </CommandList>
                </Command>
            </PopoverContent>
        </Popover>
    )
}
