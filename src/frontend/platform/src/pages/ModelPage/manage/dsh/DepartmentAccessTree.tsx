import { Button } from '@/components/bs-ui/button'
import type { DshDepartmentPolicy, DshModelUserPermission, DshSubjectPolicy } from '@/types/dsh'
import { Building2, ChevronDown, ChevronRight, Loader2, Pencil, UserRound } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { policyKey, type PolicyDrafts } from './SubjectPolicyControls'
import { useUserPolicyDrafts, userDraftOf } from './useUserPolicyDrafts'
import { QuotaInput } from './QuotaInput'
import { formatWanQuota } from './quotaUnits'
import { AccessMembersProvider, useAccessMembers, useDelayedMemberLoading } from './useAccessMembers'

import { ReauthorizeSeat, SeatRestoreContext } from './ReauthorizeSeat'

type UserDrafts = ReturnType<typeof useUserPolicyDrafts>
interface Props {
    tenantId: number
    modelId: number
    items: DshDepartmentPolicy[]
    drafts: PolicyDrafts
    query: string
    users: UserDrafts
    saving: boolean
    refresh: number
    savedRevision: number
    onQueryClear: () => void
    onDepartmentChange: (item: DshSubjectPolicy, value: string) => void
}
type Node = { item: DshDepartmentPolicy; children: Node[] }
const columns = 'grid grid-cols-[minmax(140px,1fr)_minmax(230px,1.2fr)_minmax(130px,0.8fr)_152px] items-center gap-3 px-3'

function departmentQuota(item: DshDepartmentPolicy, items: DshDepartmentPolicy[], drafts: PolicyDrafts): number {
    let current: DshDepartmentPolicy | undefined = item
    let quota = 0
    const visited = new Set<number>()
    while (current && !visited.has(current.subject_id)) {
        visited.add(current.subject_id)
        const draft = drafts[policyKey(current)]
        quota = Math.max(quota, draft ? Number(draft.limit) || 0 : current.enabled ? current.monthly_token_limit : 0)
        const parentId = current.parent_id
        current = items.find((entry) => entry.subject_id === parentId)
    }
    return quota
}

function inheritedQuota(item: DshModelUserPermission, departments: DshDepartmentPolicy[], drafts: PolicyDrafts): number {
    const quotas = item.sources.filter((source) => source.subject_type === 'ROLE').map((source) => source.monthly_token_limit)
    for (const membership of item.departments) {
        const department = departments.find((entry) => entry.subject_id === membership.id)
        if (department) quotas.push(departmentQuota(department, departments, drafts))
    }
    return Math.max(0, ...quotas)
}

function MemberRows({
    items,
    users,
    saving,
    departments,
    departmentDrafts,
    showDepartment,
    savedRevision,
}: {
    items: DshModelUserPermission[]
    users: UserDrafts
    saving: boolean
    departments: DshDepartmentPolicy[]
    departmentDrafts: PolicyDrafts
    showDepartment: boolean
    savedRevision: number
}) {
    const { t } = useTranslation()
    const [editing, setEditing] = useState<number | null>(null)
    useEffect(() => setEditing(null), [savedRevision])
    return (
        <>
            {items.map((item) => {
                const entry = users.entries[item.user_id]
                const saved = entry?.saved ?? item
                const draft = entry?.draft ?? userDraftOf(item)
                const status = item.access_status ?? 'UNAVAILABLE'
                const inherited = inheritedQuota(saved, departments, departmentDrafts)
                const value = draft.enabled ? draft.limit : String(inherited)
                const disabled = saving || Boolean(entry?.operationId)
                return (
                    <div key={item.user_id}>
                    <div
                        className={columns + ' min-h-16 border-b border-border/40 py-2 hover:bg-muted/30'}
                    >
                        <div
                            className="relative flex min-w-0 items-center gap-2"
                        >
                            <UserRound aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <div className="min-w-0">
                                <p className="break-words">{saved.user_name}</p>
                                <p className="text-xs text-muted-foreground">{showDepartment && (saved.departments.map((department) => department.name).join(' / ') || t('dsh.unassignedDepartment'))}</p>
                            </div>
                        </div>
                        <div className="space-y-1">
                            <div className="flex items-center gap-2">
                                {editing === item.user_id ? <div className="w-36"><QuotaInput label={saved.user_name + ' · ' + t('dsh.configuredQuotaWan')} value={value} disabled={disabled} onChange={(limit) => users.change(saved, { enabled: true, limit })} /></div> : <span className="font-medium tabular-nums">{formatWanQuota(Number(value))}</span>}
                                {editing !== item.user_id && <Button variant="ghost" size="sm" className="h-7 w-7 p-0" aria-label={saved.user_name + ' · ' + t('dsh.editQuota')} disabled={disabled} onClick={() => setEditing(item.user_id)}><Pencil aria-hidden className="h-3.5 w-3.5" /></Button>}
                                {draft.enabled && <span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground">{t('dsh.individualQuota')}</span>}
                            </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <span
                                className={'inline-flex h-6 items-center whitespace-nowrap text-xs font-medium ' +
                                    (status === 'AUTHORIZED' || status === 'PENDING_LOGIN'
                                        ? 'text-green-600'
                                        : status === 'REVOKED'
                                          ? 'text-red-600'
                                          : status === 'SEAT_LIMIT_REACHED'
                                            ? 'text-amber-600'
                                            : 'text-muted-foreground')}
                            >
                                {t('dsh.access_' + status)}
                            </span>
                            {status === 'REVOKED' && <ReauthorizeSeat userId={item.user_id} name={saved.user_name} disabled={saving} />}
                        </div>
                        <div className="flex h-9 items-center justify-end">
                            {draft.enabled && <Button variant="outline" size="sm" className="h-9 whitespace-nowrap px-3 text-xs" disabled={disabled} onClick={() => { users.change(saved, { enabled: false, limit: '0' }); setEditing(null) }}>{t('dsh.useDepartmentQuota')}</Button>}
                        </div>
                    </div>
                    </div>
                )
            })}
        </>
    )
}

function treeOf(items: DshDepartmentPolicy[]) {
    const map = new Map<number, Node>(items.map((item) => [item.subject_id, { item, children: [] }]))
    const roots: Node[] = []
    for (const node of map.values()) {
        const parent = node.item.parent_id ? map.get(node.item.parent_id) : undefined
        if (parent) parent.children.push(node)
        else roots.push(node)
    }
    return roots
}

function DepartmentBranch({ node, depth, selected, choose, query }: {
    node: Node; depth: number; selected: number; choose: (id: number) => void; query: string
}) {
    const [open, setOpen] = useState(depth === 0)
    const matches = (branch: Node): boolean => branch.item.name.toLocaleLowerCase().includes(query) || branch.children.some(matches)
    if (query && !matches(node)) return null
    return <div>
        <div className={'flex items-center rounded-md ' + (selected === node.item.subject_id ? 'bg-primary/10 text-primary' : 'hover:bg-muted/50')} style={{ paddingLeft: depth * 16 }}>
            {node.children.length > 0 ? <button type="button" aria-label={node.item.name + ' · ' + '▾'} aria-expanded={open || !!query} className="p-1" onClick={() => setOpen(!open)}>{open || query ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}</button> : <span className="w-6 shrink-0" />}
            <button type="button" aria-current={selected === node.item.subject_id ? 'true' : undefined} className="flex min-h-10 min-w-0 flex-1 items-center gap-2 py-2 pr-2 text-left" onClick={() => choose(node.item.subject_id)}>
                <Building2 aria-hidden className="h-4 w-4 shrink-0" /><span className="break-words">{node.item.name}</span>
            </button>
        </div>
        {(open || !!query) && node.children.map((child) => <DepartmentBranch key={child.item.subject_id} node={child} depth={depth + 1} selected={selected} choose={choose} query={query} />)}
    </div>
}

function DepartmentPane({ props, selected }: { props: Props; selected: number }) {
    const { t } = useTranslation()
    const [editing, setEditing] = useState(false)
    const query = props.query.trim()
    const item = props.items.find((department) => department.subject_id === selected)
    const state = useAccessMembers(props.modelId, query ? undefined : selected, query || undefined, props.users.remember)
    const loading = useDelayedMemberLoading(state.loading)
    useEffect(() => setEditing(false), [selected, props.savedRevision])
    const effective = item ? departmentQuota(item, props.items, props.drafts) : 0
    const draft = item ? props.drafts[policyKey(item)] : undefined
    return <section className="min-w-0 flex-1 p-5" aria-label={t('dsh.departmentQuotaPanel')}>
        <h3 className="text-base font-semibold">{query ? t('dsh.quotaSearchResults') : item?.name ?? t('dsh.unassignedDepartment')}</h3>
        {!query && item && <div className="my-4 rounded-lg bg-muted/40 p-4">
            <div className="flex items-center justify-between gap-4">
                <div>
                    <p className="text-xs text-muted-foreground">{t('dsh.departmentDefaultQuota')}</p>
                    <div className="mt-1 flex items-center gap-2">
                        {editing ? <div className="w-44"><QuotaInput label={item.name + ' · ' + t('dsh.configuredQuotaWan')} value={draft?.limit ?? String(item.enabled ? item.monthly_token_limit : 0)} disabled={props.saving} onChange={(limit) => props.onDepartmentChange(item, limit)} /></div> : <span className="text-xl font-semibold tabular-nums">{formatWanQuota(effective)}</span>}
                        <span className="text-sm text-muted-foreground">{t('dsh.wanPerPersonMonth')}</span>
                        {!editing && <Button variant="ghost" size="sm" className="h-7 w-7 p-0" aria-label={item.name + ' · ' + t('dsh.editQuota')} disabled={props.saving} onClick={() => setEditing(true)}><Pencil aria-hidden className="h-3.5 w-3.5" /></Button>}
                    </div>
                </div>
            </div>
        </div>}
        <p className="my-4 text-xs leading-5 text-muted-foreground">{t('dsh.inlineQuotaHelp')}</p>
        <div className="overflow-x-auto rounded-lg border">
            <div className="min-w-[720px]">
                <div className={columns + ' min-h-11 border-b bg-muted/30 py-3 text-xs text-muted-foreground'}>
                    <span>{t('dsh.quotaMember')}</span><span>{t('dsh.monthlyQuotaWan')}</span><span>{t('dsh.authorizationAndStatus')}</span><span className="text-right">{t('dsh.quotaActions')}</span>
                </div>
                <MemberRows savedRevision={props.savedRevision} key={selected + query} departments={props.items} departmentDrafts={props.drafts} showDepartment={Boolean(query)} items={state.page?.items ?? []} users={props.users} saving={props.saving || state.loading || state.error} />
                {loading && <p role="status" className="flex items-center gap-2 p-4 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t('dsh.loading')}</p>}
                {state.error && <div role="alert" className="p-4">{t('dsh.unavailable')} <Button variant="outline" size="sm" onClick={state.retry}>{t('dsh.refresh')}</Button></div>}
                {!state.loading && !state.error && state.page?.items.length === 0 && <p className="p-8 text-center text-muted-foreground">{t('dsh.empty')}</p>}
                {state.page?.has_more && <div className="p-3 text-right"><Button variant="outline" size="sm" disabled={state.loading || props.saving} onClick={state.more}>{t('dsh.loadMore')}</Button></div>}
            </div>
        </div>
    </section>
}

export function DepartmentAccessTree(props: Props) {
    const { t } = useTranslation()
    const [seatRevision, setSeatRevision] = useState(0)
    const [selected, setSelected] = useState(props.items[0]?.subject_id ?? 0)
    const roots = useMemo(() => treeOf(props.items), [props.items])
    const choose = (id: number) => { setSelected(id); props.onQueryClear() }
    return <SeatRestoreContext.Provider value={{ tenantId: props.tenantId, onRestored: () => setSeatRevision((value) => value + 1) }}>
        <AccessMembersProvider modelId={props.modelId} refresh={props.refresh + seatRevision}>
            <div className="flex min-h-full min-w-[880px] text-sm leading-5">
                <nav aria-label={t('dsh.quotaDepartments')} className="w-60 shrink-0 border-r bg-muted/10 p-3 text-[13px]">
                    <p className="mb-3 px-2 text-xs font-medium text-muted-foreground">{t('dsh.quotaDepartments')}</p>
                    {roots.map((node) => <DepartmentBranch key={node.item.subject_id} node={node} depth={0} selected={selected} choose={choose} query={props.items.some((item) => item.name.toLocaleLowerCase().includes(props.query.trim().toLocaleLowerCase())) ? props.query.trim().toLocaleLowerCase() : ''} />)}
                    <button type="button" aria-current={selected === 0 ? 'true' : undefined} className={'mt-2 flex min-h-10 w-full items-center rounded-md px-6 text-left ' + (selected === 0 ? 'bg-primary/10 text-primary' : 'hover:bg-muted/50')} onClick={() => choose(0)}>{t('dsh.unassignedDepartment')}</button>
                </nav>
                <DepartmentPane props={props} selected={selected} />
            </div>
        </AccessMembersProvider>
    </SeatRestoreContext.Provider>
}
