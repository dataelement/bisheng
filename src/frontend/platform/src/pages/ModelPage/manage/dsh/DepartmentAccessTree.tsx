import { Badge } from '@/components/bs-ui/badge'
import { Button } from '@/components/bs-ui/button'
import type { DshDepartmentPolicy, DshModelUserPermission, DshSubjectPolicy } from '@/types/dsh'
import { Building2, ChevronDown, ChevronRight, Loader2, UserRound } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { policyKey, type PolicyDrafts } from './SubjectPolicyControls'
import { useUserPolicyDrafts, userDraftOf } from './useUserPolicyDrafts'
import { QuotaInput } from './QuotaInput'
import { formatWanQuota } from './quotaUnits'
import { AccessMembersProvider, useAccessMembers, useDelayedMemberLoading } from './useAccessMembers'

type UserDrafts = ReturnType<typeof useUserPolicyDrafts>
interface Props {
    modelId: number
    items: DshDepartmentPolicy[]
    drafts: PolicyDrafts
    query: string
    users: UserDrafts
    saving: boolean
    refresh: number
    onDepartmentChange: (item: DshSubjectPolicy, value: string) => void
}
type Node = { item: DshDepartmentPolicy; children: Node[] }
const columns = 'grid grid-cols-[minmax(280px,1fr)_200px_200px_160px] items-center gap-3 px-3'

function MemberRows({
    items,
    users,
    saving,
    depth,
}: {
    items: DshModelUserPermission[]
    users: UserDrafts
    saving: boolean
    depth: number
}) {
    const { t } = useTranslation()
    return (
        <>
            {items.map((item) => {
                const entry = users.entries[item.user_id]
                const saved = entry?.saved ?? item
                const draft = entry?.draft ?? userDraftOf(item)
                const status = item.access_status ?? 'UNAVAILABLE'
                return (
                    <div
                        key={item.user_id}
                        className={columns + ' min-h-14 border-b border-border/40 py-2 hover:bg-muted/30'}
                    >
                        <div
                            className="relative flex min-w-0 items-center gap-2"
                            style={{ paddingLeft: depth * 24 + 24 }}
                        >
                            <span
                                aria-hidden
                                className="absolute w-4 border-t"
                                style={{ left: depth * 24 }}
                            />
                            <UserRound aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <div className="min-w-0">
                                <p className="break-words">{saved.user_name}</p>
                                <p className="text-xs text-muted-foreground">ID: {saved.user_id}</p>
                            </div>
                        </div>
                        <QuotaInput
                            label={saved.user_name + ' · ' + t('dsh.configuredQuotaWan')}
                            value={draft.limit}
                            disabled={saving || Boolean(entry?.operationId)}
                            onChange={(limit) => users.change(saved, { limit })}
                        />
                        <div>
                            <span className="tabular-nums">{formatWanQuota(item.monthly_token_limit)}</span>
                            {item.sources.some((source) => source.winning) && <p className="mt-1 text-xs text-muted-foreground">
                                {t('dsh.quotaSource', { name: item.sources.filter((source) => source.winning).map((source) => source.name).join(', ') })}
                            </p>}
                        </div>
                        <Badge
                            title={status === 'PENDING_LOGIN' ? t('dsh.pendingLoginHelp') : undefined}
                            variant={status === 'AUTHORIZED' ? 'secondary' : 'outline'}
                            className={
                                'w-fit whitespace-nowrap ' +
                                (status === 'AUTHORIZED'
                                    ? 'text-green-600'
                                    : status === 'SEAT_LIMIT_REACHED'
                                      ? 'text-amber-600'
                                      : '')
                            }
                        >
                            {t('dsh.access_' + status)}
                        </Badge>
                    </div>
                )
            })}
        </>
    )
}

function MemberList({
    modelId,
    departmentId,
    users,
    saving,
    depth,
    onLoadingChange,
}: {
    modelId: number
    departmentId: number
    users: UserDrafts
    saving: boolean
    depth: number
    onLoadingChange: (loading: boolean) => void
}) {
    const { t } = useTranslation()
    const state = useAccessMembers(modelId, departmentId, undefined, users.remember)
    useEffect(() => {
        onLoadingChange(state.loading)
        return () => onLoadingChange(false)
    }, [state.loading, onLoadingChange])
    return (
        <>
            <MemberRows
                items={state.page?.items ?? []}
                users={users}
                saving={saving || state.loading || state.error}
                depth={depth}
            />
            {(state.error || state.page?.has_more) && (
                <div className="py-1 text-sm text-muted-foreground" style={{ paddingLeft: depth * 24 + 48 }}>
                    {state.error && (
                        <Button variant="outline" size="sm" onClick={state.retry}>
                            {t('dsh.refresh')}
                        </Button>
                    )}
                    {state.page?.has_more && (
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={state.loading || saving}
                            onClick={state.more}
                        >
                            {t('dsh.loadMore')}
                        </Button>
                    )}
                </div>
            )}
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

function Branch({
    node,
    depth,
    props,
    searchItems,
    parentMatched = false,
    parentQuota = 0,
}: {
    node: Node
    depth: number
    props: Props
    searchItems?: DshModelUserPermission[]
    parentMatched?: boolean
    parentQuota?: number
}) {
    const { t } = useTranslation()
    const { item } = node
    const [expanded, setExpanded] = useState(depth === 0)
    const [loading, setLoading] = useState(false)
    const showLoading = useDelayedMemberLoading(loading)
    const query = props.query.trim().toLocaleLowerCase()
    const departmentMatched = parentMatched || Boolean(query && item.name.toLocaleLowerCase().includes(query))
    const directHits =
        searchItems?.filter((user) =>
            user.departments.some((department) => department.id === item.subject_id),
        ) ?? []
    const containsHit = (branch: Node): boolean =>
        branch.item.name.toLocaleLowerCase().includes(query) ||
        Boolean(
            searchItems?.some((user) =>
                user.departments.some((department) => department.id === branch.item.subject_id),
            ),
        ) ||
        branch.children.some(containsHit)
    if (query && !departmentMatched && !containsHit(node)) return null
    const open = query ? true : expanded
    const draft = props.drafts[policyKey(item)]
    const value = draft?.limit ?? String(item.enabled ? item.monthly_token_limit : 0)
    const effectiveQuota = Math.max(parentQuota, item.enabled ? item.monthly_token_limit : 0)
    return (
        <div>
            <div className={columns + ' min-h-12 py-2 hover:bg-muted/30'}>
                <div className="relative flex min-w-0 items-center gap-2" style={{ paddingLeft: depth * 24 }}>
                    {depth > 0 && (
                        <span
                            aria-hidden
                            className="absolute -left-0 w-4 border-t"
                            style={{ left: (depth - 1) * 24 + 12 }}
                        />
                    )}
                    <button
                        type="button"
                        aria-label={item.name}
                        aria-expanded={open}
                        aria-busy={open && loading}
                        disabled={Boolean(query)}
                        className="flex min-h-8 min-w-0 items-center gap-2 rounded-sm text-left text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                        onClick={() => setExpanded(!expanded)}
                    >
                        {open && showLoading ? (
                            <Loader2
                                role="status"
                                aria-label={t('dsh.loading')}
                                className="h-4 w-4 shrink-0 animate-spin motion-reduce:animate-pulse"
                            />
                        ) : open ? (
                            <ChevronDown aria-hidden className="h-4 w-4 shrink-0" />
                        ) : (
                            <ChevronRight aria-hidden className="h-4 w-4 shrink-0" />
                        )}
                        <Building2 aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <span className="break-words">{item.name}</span>
                    </button>
                </div>
                <QuotaInput
                    label={item.name + ' · ' + t('dsh.configuredQuotaWan')}
                    value={value}
                    disabled={props.saving}
                    onChange={(limit) => props.onDepartmentChange(item, limit)}
                />
                <span className="tabular-nums">{formatWanQuota(effectiveQuota)}</span>
                <Badge
                    variant={effectiveQuota > 0 ? 'secondary' : 'outline'}
                    className={'w-fit whitespace-nowrap ' + (effectiveQuota > 0 ? 'text-green-600' : '')}
                >
                    {t(effectiveQuota > 0 ? 'dsh.access_AUTHORIZED' : 'dsh.access_UNAUTHORIZED')}
                </Badge>
            </div>
            {open && (
                <div className="relative">
                    <span
                        aria-hidden
                        className="pointer-events-none absolute bottom-0 top-0 border-l"
                        style={{ left: depth * 24 + 20 }}
                    />
                    {!query || departmentMatched ? (
                        <MemberList
                            modelId={props.modelId}
                            departmentId={item.subject_id}
                            onLoadingChange={setLoading}
                            users={props.users}
                            saving={props.saving}
                            depth={depth}
                        />
                    ) : (
                        <MemberRows
                            items={directHits}
                            users={props.users}
                            saving={props.saving}
                            depth={depth}
                        />
                    )}
                    {node.children.map((child) => (
                        <Branch
                            key={child.item.subject_id}
                            node={child}
                            depth={depth + 1}
                            props={props}
                            searchItems={searchItems}
                            parentMatched={departmentMatched}
                            parentQuota={effectiveQuota}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

function SearchTree({ props, roots }: { props: Props; roots: Node[] }) {
    const { t } = useTranslation()
    const state = useAccessMembers(props.modelId, undefined, props.query.trim(), props.users.remember)
    return (
        <>
            {state.loading && (
                <p role="status" className="p-3">
                    {t('dsh.loading')}
                </p>
            )}
            {state.error && (
                <div role="alert" className="p-3">
                    {t('dsh.unavailable')} <Button onClick={state.retry}>{t('dsh.refresh')}</Button>
                </div>
            )}
            {roots.map((node) => (
                <Branch
                    key={node.item.subject_id}
                    node={node}
                    depth={0}
                    props={props}
                    searchItems={state.page?.items ?? []}
                />
            ))}
            {!!state.page?.items.some((user) => !user.departments.length) && (
                <>
                    <p className="p-3 font-medium">{t('dsh.unassignedDepartment')}</p>
                    <MemberRows
                        items={state.page.items.filter((user) => !user.departments.length)}
                        users={props.users}
                        saving={props.saving}
                        depth={0}
                    />
                </>
            )}
            {state.page?.has_more && (
                <div className="flex justify-end p-3">
                    <Button disabled={state.loading} onClick={state.more}>
                        {t('dsh.loadMore')}
                    </Button>
                </div>
            )}
            {!state.loading &&
                !state.error &&
                state.page?.items.length === 0 &&
                !props.items.some((item) =>
                    item.name.toLocaleLowerCase().includes(props.query.trim().toLocaleLowerCase()),
                ) && <p className="p-6 text-center text-sm text-muted-foreground">{t('dsh.empty')}</p>}
        </>
    )
}

export function DepartmentAccessTree(props: Props) {
    const { t } = useTranslation()
    const roots = useMemo(() => treeOf(props.items), [props.items])
    const [unassignedOpen, setUnassignedOpen] = useState(false)
    const [loading, setLoading] = useState(false)
    const showLoading = useDelayedMemberLoading(loading)
    return (
        <AccessMembersProvider modelId={props.modelId} refresh={props.refresh}>
            <div className="min-w-[900px] text-sm leading-5">
                <p className="px-3 py-2 text-sm text-muted-foreground">{t('dsh.quotaInheritanceHelp')}</p>
                <div
                    className={
                        columns +
                        ' sticky top-0 z-10 min-h-12 border-b bg-background text-sm text-muted-foreground'
                    }
                >
                    <span>{t('dsh.departmentAndMember')}</span>
                    <span>{t('dsh.configuredQuotaWan')}</span>
                    <span>{t('dsh.effectiveQuotaWan')}</span>
                    <span>{t('dsh.authorizationAndStatus')}</span>
                </div>
                {props.query.trim() ? (
                    <SearchTree props={props} roots={roots} />
                ) : (
                    <>
                        {roots.map((node) => (
                            <Branch key={node.item.subject_id} node={node} depth={0} props={props} />
                        ))}
                        <button
                            type="button"
                            className="flex min-h-12 items-center gap-2 rounded-sm px-3 text-sm font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                            aria-expanded={unassignedOpen}
                            aria-busy={unassignedOpen && loading}
                            onClick={() => setUnassignedOpen(!unassignedOpen)}
                        >
                            {unassignedOpen && showLoading ? (
                                <Loader2
                                    role="status"
                                    aria-label={t('dsh.loading')}
                                    className="h-4 w-4 animate-spin motion-reduce:animate-pulse"
                                />
                            ) : unassignedOpen ? (
                                <ChevronDown className="h-4 w-4" />
                            ) : (
                                <ChevronRight className="h-4 w-4" />
                            )}
                            {t('dsh.unassignedDepartment')}
                        </button>
                        {unassignedOpen && (
                            <MemberList
                                modelId={props.modelId}
                                departmentId={0}
                                onLoadingChange={setLoading}
                                users={props.users}
                                saving={props.saving}
                                depth={0}
                            />
                        )}
                    </>
                )}
            </div>
        </AccessMembersProvider>
    )
}
