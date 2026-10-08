import { TreeDepartmentSelect } from '@/components/bs-comp/department/TreeDepartmentSelect'
import { Button } from '@/components/bs-ui/button'
import { Tabs, TabsList, TabsTrigger } from '@/components/bs-ui/tabs'
import {
    getDshUsagePresentationOverview as getDshUsageOverview,
    getDshUsagePresentationSummary as getDshUsageTimeSummary,
} from '@/controllers/API/dshUsagePresentation'
import { userContext } from '@/contexts/userContext'
import type { DshUsageOverviewUser, DshUsageTimeSummary } from '@/types/dsh'
import { useContext, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { UsageRangeSelect } from './UsageRangeSelect'
import { UsageSummaryView } from './UsageSummaryView'
import { UsageUserSelect } from './UsageUserSelect'
import {
    localInputValue,
    usageGranularity,
    usagePresetRange,
    type UsagePreset,
    type UsageRange,
} from './usageRange'

type Dimension = 'user' | 'department'

interface PolicyViewProps {
    toolbarTarget?: HTMLDivElement | null
}

export function PolicyView({ toolbarTarget }: PolicyViewProps) {
    const { t } = useTranslation()
    const { user: currentUser } = useContext(userContext)
    const [dimension, setDimension] = useState<Dimension>('user')
    const [department, setDepartment] = useState<{ id: number; name: string } | null>(null)
    const [user, setUser] = useState<DshUsageOverviewUser | null>(null)
    const [preset, setPreset] = useState<UsagePreset>('year')
    const [selectedRange, setRange] = useState<UsageRange>(() => usagePresetRange('year'))
    const range = useMemo(() => selectedRange, [selectedRange])
    const [summary, setSummary] = useState<DshUsageTimeSummary | null>(null)
    const [error, setError] = useState(false)
    const [defaultUserLoading, setDefaultUserLoading] = useState(true)
    const [defaultUserError, setDefaultUserError] = useState(false)
    const targetId = dimension === 'department' ? department?.id : user?.user_id
    const hasTarget = dimension === 'department' || !!user
    const tenantLabel = [currentUser?.tenant_name || currentUser?.leaf_tenant_name, t('dsh.entireTenant')]
        .filter(Boolean)
        .join(' / ')

    useEffect(() => {
        if (dimension !== 'user' || user) return
        const abort = new AbortController()
        setDefaultUserLoading(true)
        setDefaultUserError(false)
        const loadDefaultUser = async () => {
            const page = await getDshUsageOverview({ ...range, limit: 20 }, abort.signal)
            let preferred =
                page.items.find((item) => item.user_name === 'admin') ??
                page.items.find((item) => item.user_id === Number(currentUser?.user_id))
            if (!preferred && currentUser?.user_name && page.has_more) {
                const matches = await getDshUsageOverview(
                    { ...range, keyword: currentUser.user_name, limit: 100 },
                    abort.signal,
                )
                preferred = matches.items.find((item) => item.user_id === Number(currentUser.user_id))
            }
            if (!abort.signal.aborted) setUser((selected) => selected ?? preferred ?? page.items[0] ?? null)
        }
        loadDefaultUser()
            .catch(() => {
                if (!abort.signal.aborted) setDefaultUserError(true)
            })
            .finally(() => {
                if (!abort.signal.aborted) setDefaultUserLoading(false)
            })
        return () => abort.abort()
    }, [dimension, user, currentUser?.user_id, currentUser?.user_name, range])

    useEffect(() => {
        const abort = new AbortController()
        setSummary(null)
        setError(false)
        if (!hasTarget) return
        const request =
            dimension === 'department'
                ? getDshUsageOverview(
                      {
                          ...range,
                          granularity: usageGranularity(range),
                          departmentId: targetId,
                          limit: 20,
                          includeSummary: true,
                      },
                      abort.signal,
                  ).then((result) => result.summary ?? null)
                : getDshUsageTimeSummary(
                      String(targetId),
                      { ...range, granularity: usageGranularity(range) },
                      abort.signal,
                  )
        request
            .then((result) => {
                if (!abort.signal.aborted) {
                    setSummary(result)
                    setError(!result)
                }
            })
            .catch(() => {
                if (!abort.signal.aborted) setError(true)
            })
        return () => abort.abort()
    }, [dimension, targetId, hasTarget, range])

    const handleUser = (next: DshUsageOverviewUser) => {
        setUser(next)
        setDimension('user')
    }
    const handleRange = (next: UsagePreset, nextRange: UsageRange) => {
        setPreset(next)
        setRange(nextRange)
    }
    const targetName =
        dimension === 'department'
            ? (department?.name ?? tenantLabel)
            : [user?.department_name, user?.user_name].filter(Boolean).join(' / ')

    const toolbar = (
        <div
            className="flex max-w-full flex-wrap items-center justify-end gap-2"
            aria-label={t('dsh.usageFilters')}
        >
            <Tabs
                value={dimension}
                onValueChange={(value) => {
                    setDimension(value as Dimension)
                }}
            >
                <TabsList>
                    <TabsTrigger value="department">{t('dsh.byDepartment')}</TabsTrigger>
                    <TabsTrigger value="user">{t('dsh.byUser')}</TabsTrigger>
                </TabsList>
            </Tabs>
            {dimension === 'department' ? (
                <TreeDepartmentSelect
                    allowNone
                    noneLabel={tenantLabel}
                    value={department?.id ?? null}
                    onChange={(id, node) => {
                        setDepartment(id && node ? { id, name: node.name } : null)
                    }}
                    placeholder={t('dsh.selectDepartment')}
                    searchPlaceholder={t('dsh.searchDepartments')}
                    modal={false}
                    className="w-72 max-w-full"
                />
            ) : (
                <UsageUserSelect value={user} range={range} onChange={handleUser} />
            )}
            <UsageRangeSelect preset={preset} onChange={handleRange} />
            <Button variant="outline" className="h-9" onClick={() => setRange(usagePresetRange(preset))}>
                {t('dsh.refresh')}
            </Button>
        </div>
    )

    return (
        <section className="space-y-4">
            {toolbarTarget
                ? createPortal(toolbar, toolbarTarget)
                : toolbarTarget === undefined
                  ? toolbar
                  : null}
            {!hasTarget ? (
                <div
                    role={defaultUserError ? 'alert' : 'status'}
                    className="rounded-lg border p-10 text-center text-sm text-muted-foreground"
                >
                    {t(
                        defaultUserError
                            ? 'dsh.unavailable'
                            : defaultUserLoading
                              ? 'dsh.loading'
                              : 'dsh.empty',
                    )}
                </div>
            ) : (
                <>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <h2 className="text-base font-medium">{targetName}</h2>
                        <span className="text-xs text-muted-foreground">
                            {localInputValue(range.startAt).replace('T', ' ')} —{' '}
                            {localInputValue(range.endAt).replace('T', ' ')}
                        </span>
                    </div>
                    {summary ? (
                        <UsageSummaryView summary={summary} />
                    ) : (
                        <p role={error ? 'alert' : 'status'} className="py-8 text-sm text-muted-foreground">
                            {t(error ? 'dsh.usageRangeUnavailable' : 'dsh.loading')}
                        </p>
                    )}
                </>
            )}
        </section>
    )
}
