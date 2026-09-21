import { Badge } from '@/components/bs-ui/badge'
import { Button } from '@/components/bs-ui/button'
import { Checkbox } from '@/components/bs-ui/checkBox'
import { Input } from '@/components/bs-ui/input'
import { getDshModelUserPermissions } from '@/controllers/API/dsh'
import type {
    DshDepartmentPolicy,
    DshModelUserPermission,
    DshRolePolicy,
    DshSubjectPolicy,
    DshSubjectPolicyInventory,
} from '@/types/dsh'
import { Building2, ChevronDown, ChevronRight, Loader2, UserRound } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

export type PolicyDraft = { enabled: boolean; limit: string }
export type PolicyDrafts = Record<string, PolicyDraft>
type DepartmentTreeNode = { item: DshDepartmentPolicy; children: DepartmentTreeNode[] }
type DepartmentMembersState = {
    items: DshModelUserPermission[]
    nextCursor: string | null
    hasMore: boolean
    loading: boolean
    loadingMore: boolean
    error: boolean
}

export const policyKey = (item: DshSubjectPolicy) => `${item.subject_type}:${item.subject_id}`
export const draftOf = (item: DshSubjectPolicy, drafts: PolicyDrafts): PolicyDraft =>
    drafts[policyKey(item)] ?? {
        enabled: item.enabled,
        limit: String(item.monthly_token_limit),
    }

export function initialDrafts(inventory: DshSubjectPolicyInventory): PolicyDrafts {
    return [...inventory.departments, ...inventory.roles].reduce<PolicyDrafts>((result, item) => {
        result[policyKey(item)] = {
            enabled: item.enabled,
            limit: String(item.monthly_token_limit),
        }
        return result
    }, {})
}

export function isDraftValid(draft: PolicyDraft): boolean {
    if (!draft.enabled) return true
    if (!/^\d+$/.test(draft.limit)) return false
    const value = Number(draft.limit)
    return Number.isSafeInteger(value) && value >= 0
}

export function isDraftDirty(item: DshSubjectPolicy, draft: PolicyDraft): boolean {
    return (
        draft.enabled !== item.enabled || (draft.enabled && Number(draft.limit) !== item.monthly_token_limit)
    )
}

function buildDepartmentTree(items: DshDepartmentPolicy[]): DepartmentTreeNode[] {
    const nodes = new Map<number, DepartmentTreeNode>()
    const roots: DepartmentTreeNode[] = []
    items.forEach((item) => nodes.set(item.subject_id, { item, children: [] }))
    items.forEach((item) => {
        const node = nodes.get(item.subject_id)!
        const parent = item.parent_id ? nodes.get(item.parent_id) : undefined
        if (parent) parent.children.push(node)
        else roots.push(node)
    })
    return roots
}

function filterDepartmentTree(nodes: DepartmentTreeNode[], query: string): DepartmentTreeNode[] {
    if (!query) return nodes
    return nodes.flatMap((node) => {
        const children = filterDepartmentTree(node.children, query)
        if (node.item.name.toLocaleLowerCase().includes(query) || children.length)
            return [{ ...node, children }]
        return []
    })
}

function findInheritedDepartment(
    item: DshDepartmentPolicy,
    byId: Map<number, DshDepartmentPolicy>,
    drafts: PolicyDrafts,
): DshDepartmentPolicy | null {
    let parentId = item.parent_id
    while (parentId) {
        const parent = byId.get(parentId)
        if (!parent) return null
        if (draftOf(parent, drafts).enabled) return parent
        parentId = parent.parent_id
    }
    return null
}

function departmentIsSelected(
    item: DshDepartmentPolicy,
    byId: Map<number, DshDepartmentPolicy>,
    drafts: PolicyDrafts,
): boolean {
    return draftOf(item, drafts).enabled || Boolean(findInheritedDepartment(item, byId, drafts))
}

function hasSelectedDescendant(
    node: DepartmentTreeNode,
    byId: Map<number, DshDepartmentPolicy>,
    drafts: PolicyDrafts,
): boolean {
    return node.children.some(
        (child) =>
            departmentIsSelected(child.item, byId, drafts) || hasSelectedDescendant(child, byId, drafts),
    )
}

export function DepartmentPolicyTree({
    items,
    drafts,
    query,
    modelId,
    saving,
    onDraftChange,
}: {
    items: DshDepartmentPolicy[]
    drafts: PolicyDrafts
    query: string
    modelId: number
    saving: boolean
    onDraftChange: (item: DshSubjectPolicy, patch: Partial<PolicyDraft>) => void
}) {
    const { t } = useTranslation()
    const [expanded, setExpanded] = useState<Set<number>>(
        () => new Set(buildDepartmentTree(items).map((node) => node.item.subject_id)),
    )
    const [members, setMembers] = useState<Record<number, DepartmentMembersState>>({})
    const tree = useMemo(() => buildDepartmentTree(items), [items])
    const byId = useMemo(() => new Map(items.map((item) => [item.subject_id, item])), [items])
    const normalizedQuery = query.trim().toLocaleLowerCase()
    const visibleTree = useMemo(() => filterDepartmentTree(tree, normalizedQuery), [tree, normalizedQuery])

    const loadMembers = useCallback(
        async (departmentId: number, loadMore = false) => {
            const current = members[departmentId]
            if (current?.loading || current?.loadingMore) return
            if (loadMore && (!current?.hasMore || !current.nextCursor)) return
            setMembers((value) => ({
                ...value,
                [departmentId]: {
                    items: loadMore ? (value[departmentId]?.items ?? []) : [],
                    nextCursor: value[departmentId]?.nextCursor ?? null,
                    hasMore: value[departmentId]?.hasMore ?? false,
                    loading: !loadMore,
                    loadingMore: loadMore,
                    error: false,
                },
            }))
            try {
                const page = await getDshModelUserPermissions(modelId, {
                    cursor: loadMore ? (current.nextCursor ?? undefined) : undefined,
                    limit: 50,
                    department_id: departmentId,
                    membership: 'DIRECT',
                })
                setMembers((value) => ({
                    ...value,
                    [departmentId]: {
                        items: loadMore ? [...(value[departmentId]?.items ?? []), ...page.items] : page.items,
                        nextCursor: page.next_cursor,
                        hasMore: page.has_more,
                        loading: false,
                        loadingMore: false,
                        error: false,
                    },
                }))
            } catch {
                setMembers((value) => ({
                    ...value,
                    [departmentId]: {
                        items: value[departmentId]?.items ?? [],
                        nextCursor: value[departmentId]?.nextCursor ?? null,
                        hasMore: value[departmentId]?.hasMore ?? false,
                        loading: false,
                        loadingMore: false,
                        error: true,
                    },
                }))
            }
        },
        [members, modelId],
    )

    useEffect(() => {
        expanded.forEach((id) => {
            if (!members[id]) void loadMembers(id)
        })
    }, [expanded, members, loadMembers])

    function toggle(node: DepartmentTreeNode) {
        const id = node.item.subject_id
        if (expanded.has(id)) {
            setExpanded((value) => {
                const next = new Set(value)
                next.delete(id)
                return next
            })
            return
        }
        setExpanded((value) => new Set(value).add(id))
    }

    return (
        <div className="bg-background py-1">
            {visibleTree.map((node) => (
                <DepartmentPolicyRow
                    key={node.item.subject_id}
                    node={node}
                    byId={byId}
                    drafts={drafts}
                    expanded={expanded}
                    members={members}
                    forceExpanded={Boolean(normalizedQuery)}
                    saving={saving}
                    onToggle={toggle}
                    onLoadMore={(id) => void loadMembers(id, true)}
                    onRetryMembers={(id) => void loadMembers(id)}
                    onDraftChange={onDraftChange}
                />
            ))}
            {!visibleTree.length && (
                <p className="p-6 text-center text-sm text-muted-foreground">{t('dsh.empty')}</p>
            )}
        </div>
    )
}

function DepartmentPolicyRow({
    node,
    byId,
    drafts,
    expanded,
    members,
    forceExpanded,
    saving,
    onToggle,
    onLoadMore,
    onRetryMembers,
    onDraftChange,
    depth = 0,
}: {
    node: DepartmentTreeNode
    byId: Map<number, DshDepartmentPolicy>
    drafts: PolicyDrafts
    expanded: Set<number>
    members: Record<number, DepartmentMembersState>
    forceExpanded: boolean
    saving: boolean
    onToggle: (node: DepartmentTreeNode) => void
    onLoadMore: (departmentId: number) => void
    onRetryMembers: (departmentId: number) => void
    onDraftChange: (item: DshSubjectPolicy, patch: Partial<PolicyDraft>) => void
    depth?: number
}) {
    const { t } = useTranslation()
    const item = node.item
    const draft = draftOf(item, drafts)
    const inherited = draft.enabled ? null : findInheritedDepartment(item, byId, drafts)
    const effectiveSelected = draft.enabled || Boolean(inherited)
    const indeterminate = !effectiveSelected && hasSelectedDescendant(node, byId, drafts)
    const isExpanded = forceExpanded || expanded.has(item.subject_id)
    const memberState = members[item.subject_id]
    const inheritedLimit = inherited ? draftOf(inherited, drafts).limit : ''
    const authorized = item.enabled || Boolean(findInheritedDepartment(item, byId, {}))

    return (
        <div className="relative" data-department-id={item.subject_id}>
            {depth > 0 && (
                <span
                    aria-hidden="true"
                    className="pointer-events-none absolute -left-3 top-[22px] w-3 border-t border-border"
                />
            )}
            <div className="flex min-h-11 items-center gap-2 rounded-md px-2 hover:bg-accent/60">
                <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-7 shrink-0 active:scale-[0.97]"
                    aria-label={`${t(isExpanded ? 'dsh.collapseDepartment' : 'dsh.expandDepartment')}: ${item.name}`}
                    aria-expanded={isExpanded}
                    onClick={() => onToggle(node)}
                >
                    {isExpanded ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                </Button>
                <Checkbox
                    aria-label={t('dsh.allowSubject', { name: item.name })}
                    checked={indeterminate ? 'indeterminate' : effectiveSelected}
                    disabled={saving || Boolean(inherited)}
                    onCheckedChange={(checked) => onDraftChange(item, { enabled: checked === true })}
                />
                <button
                    type="button"
                    className="flex min-w-0 flex-1 items-center gap-2 text-left text-sm"
                    aria-expanded={isExpanded}
                    onClick={() => onToggle(node)}
                >
                    <Building2 className="size-4 shrink-0 text-muted-foreground" />
                    <span className="truncate font-medium">{item.name}</span>
                </button>
                <Input
                    boxClassName="w-36 shrink-0"
                    className="h-8"
                    aria-label={t('dsh.subjectMonthlyLimit', { name: item.name })}
                    inputMode="numeric"
                    placeholder={t('dsh.monthlyTokens')}
                    value={draft.enabled ? draft.limit : inheritedLimit}
                    disabled={!draft.enabled || saving}
                    onChange={(event) => onDraftChange(item, { limit: event.target.value })}
                />
                {authorized && (
                    <Badge variant="secondary" className="shrink-0 whitespace-nowrap text-green-600">
                        {t('dsh.authorized')}
                    </Badge>
                )}
            </div>
            {isExpanded && (
                <div className="ml-[22px] border-l border-border pl-3">
                    {memberState?.loading && (
                        <div
                            className="flex items-center gap-2 py-2 pl-10 text-sm text-muted-foreground"
                            role="status"
                        >
                            <Loader2 className="size-3.5 animate-spin" />
                            {t('dsh.loading')}
                        </div>
                    )}
                    {memberState?.error && (
                        <div className="flex items-center gap-2 py-2 pl-10 text-sm text-destructive">
                            <span role="alert">{t('dsh.memberLoadFailed')}</span>
                            <Button size="sm" variant="link" onClick={() => onRetryMembers(item.subject_id)}>
                                {t('dsh.refresh')}
                            </Button>
                        </div>
                    )}
                    {memberState && !memberState.loading && !memberState.error && (
                        <div>
                            {memberState.items.map((member) => (
                                <div
                                    key={member.user_id}
                                    className="flex min-h-9 items-center gap-2 py-1 pl-10 pr-4 text-sm text-muted-foreground"
                                >
                                    <UserRound className="size-3.5 shrink-0" />
                                    <span className="min-w-0 flex-1 truncate text-foreground">
                                        {member.user_name}
                                    </span>
                                    {!!member.roles.length && (
                                        <span className="truncate text-xs">
                                            {member.roles.map((role) => role.name).join('、')}
                                        </span>
                                    )}
                                </div>
                            ))}
                            {!memberState.items.length && (
                                <p className="py-2 pl-10 text-sm text-muted-foreground">
                                    {t('dsh.noDepartmentMembers')}
                                </p>
                            )}
                            {memberState.hasMore && (
                                <div className="py-1 pl-8">
                                    <Button
                                        size="sm"
                                        variant="link"
                                        disabled={memberState.loadingMore}
                                        onClick={() => onLoadMore(item.subject_id)}
                                    >
                                        {t(memberState.loadingMore ? 'dsh.loading' : 'dsh.loadMore')}
                                    </Button>
                                </div>
                            )}
                        </div>
                    )}
                    {node.children.map((child) => (
                        <DepartmentPolicyRow
                            key={child.item.subject_id}
                            node={child}
                            byId={byId}
                            drafts={drafts}
                            expanded={expanded}
                            members={members}
                            forceExpanded={forceExpanded}
                            saving={saving}
                            onToggle={onToggle}
                            onLoadMore={onLoadMore}
                            onRetryMembers={onRetryMembers}
                            onDraftChange={onDraftChange}
                            depth={depth + 1}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

export function RolePolicyList({
    items,
    drafts,
    saving,
    onDraftChange,
}: {
    items: DshRolePolicy[]
    drafts: PolicyDrafts
    saving: boolean
    onDraftChange: (item: DshSubjectPolicy, patch: Partial<PolicyDraft>) => void
}) {
    const { t } = useTranslation()
    return (
        <div className="bg-background py-1">
            {items.map((item) => {
                const draft = draftOf(item, drafts)
                return (
                    <div
                        key={policyKey(item)}
                        className="flex min-h-11 items-center gap-3 rounded-md px-4 hover:bg-accent/60"
                    >
                        <Checkbox
                            aria-label={t('dsh.allowSubject', { name: item.name })}
                            checked={draft.enabled}
                            disabled={saving}
                            onCheckedChange={(checked) => onDraftChange(item, { enabled: checked === true })}
                        />
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.name}</span>
                        <Input
                            boxClassName="w-36 shrink-0"
                            className="h-8"
                            aria-label={t('dsh.subjectMonthlyLimit', {
                                name: item.name,
                            })}
                            inputMode="numeric"
                            placeholder={t('dsh.monthlyTokens')}
                            value={draft.enabled ? draft.limit : ''}
                            disabled={!draft.enabled || saving}
                            onChange={(event) => onDraftChange(item, { limit: event.target.value })}
                        />
                        {item.enabled && (
                            <Badge variant="secondary" className="shrink-0 whitespace-nowrap text-green-600">
                                {t('dsh.authorized')}
                            </Badge>
                        )}
                    </div>
                )
            })}
            {!items.length && (
                <p className="p-6 text-center text-sm text-muted-foreground">{t('dsh.empty')}</p>
            )}
        </div>
    )
}
