// @ts-strict-ignore
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { Alert, Button, Select } from '@bisheng/ui';
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm"

import {
  getGrantablePermissionModelsApi,
  getMyResourcePermissionsApi,
  getResourcePermissionGrantsApi,
  mutateResourceGrantsApi,
  type GrantablePermissionModel,
  type MutateResourceGrantsResult,
  type MyResourcePermissions,
  type PermissionGrantAssignee,
  type PermissionResourceType,
  type ResourcePermissionContext,
} from "@/controllers/API/permission"
import {
  Loader2,
  LockKeyhole,
  Search,
  Trash2,
} from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { canMutatePermissionAssignee } from "./assigneePolicy"
import { PermissionSubjectIdentity } from "./PermissionSubjectLayout"
import { SourceBadge } from "./SourceBadge"
import type { SubjectType } from "./types"

interface PermissionListTabProps {
  resourceType: PermissionResourceType
  resourceId: string
  context: ResourcePermissionContext
  refreshKey?: number
  pageSize?: number
  fixedSubjectType?: SubjectType
  onRosterChange?: (assignees: PermissionGrantAssignee[]) => void
  onMutationSuccess?: (result: MutateResourceGrantsResult) => void
}

function createMutationIdempotencyKey(): string {
  return `grant-mutate-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function getInheritedSourceLabel(
  assignee: PermissionGrantAssignee,
  translate: (key: string) => string,
): string {
  const resolvedName = assignee.inherited_from_name?.trim()
  if (resolvedName) return resolvedName

  const resourceType = assignee.inherited_from?.split(":", 1)[0]
  if (resourceType === "folder") return translate("roster.parentFolder")
  if (
    resourceType === "knowledge_space" ||
    resourceType === "knowledge_library"
  ) {
    return translate("roster.parentKnowledgeSpace")
  }
  return translate("roster.parentResource")
}

interface RosterRowProps {
  assignee: PermissionGrantAssignee
  context: ResourcePermissionContext
  models: GrantablePermissionModel[]
  pending: boolean
  onMove: (assignee: PermissionGrantAssignee, modelKey: string) => void
  onRemove: (assignee: PermissionGrantAssignee) => void
}

function RosterRow({
  assignee,
  context,
  models,
  pending,
  onMove,
  onRemove,
}: RosterRowProps) {
  const { t } = useTranslation("permission")
  const selectLabels = useSelectLabels();
  const editable = canMutatePermissionAssignee(assignee, context, models)
  const displayName =
    assignee.subject.name ||
    `${assignee.subject.type}:${assignee.subject.id}`
  const currentIsGrantable = models.some(
    (model) => model.key === assignee.model.key,
  )

  return (
    <article
      data-testid={`permission-assignee-${assignee.assignee_id}`}
      data-editable={String(editable)}
      className="flex min-h-[58px] items-center gap-4 border-b border-[#F2F3F5] py-3 last:border-b-0"
    >
      <PermissionSubjectIdentity type={assignee.subject.type} name={displayName} metadata={<>
        <SourceBadge source={assignee.source} />
        <span>{t(`scope.${assignee.scope.toLowerCase()}`)}</span>
        {assignee.inherited_from && <span className="truncate">· {t("roster.inheritedFrom")}: {getInheritedSourceLabel(assignee, t)}</span>}
      </>} />

      <div className="flex w-[176px] shrink-0 items-center justify-end gap-1">
        {editable ? (
          <>
            <Select {...selectLabels} aria-label={`grant.model.${assignee.assignee_id}`} variant="ghost"
              value={assignee.model.key} disabled={pending} className="min-w-0 flex-1"
              options={[...(!currentIsGrantable ? [{ value: assignee.model.key, label: assignee.model.name }] : []), ...models.map(model => ({ value: model.key, label: model.name }))]}
              onChange={value => { if (value != null) onMove(assignee, String(value)); }} />
            <button
              type="button"
              aria-label={`${t("grant.remove")}.${assignee.assignee_id}`}
              disabled={pending}
              className="flex size-8 shrink-0 items-center justify-center rounded-[6px] text-[#86909C] transition-colors hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => onRemove(assignee)}
            >
              <Trash2 aria-hidden="true" className="size-4" />
            </button>
          </>
        ) : (
          <span className="inline-flex items-center gap-1 truncate text-sm text-[#86909C]">
            {assignee.model.name}
            {assignee.protected && (
              <LockKeyhole
                aria-label={t("roster.protected")}
                className="size-3.5 shrink-0"
              />
            )}
          </span>
        )}
      </div>
    </article>
  )
}

function SummaryView({ summary }: { summary: MyResourcePermissions }) {
  const { t } = useTranslation("permission")
  return (
    <section className="rounded-lg border border-[#EBECF0] bg-[#F7F8FA] p-4">
      <p className="text-sm font-medium text-[#212121]">
        {t("roster.summaryOnly")}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {summary.actions.map((action) => (
          <span
            key={action}
            className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary"
          >
            {action}
          </span>
        ))}
      </div>
    </section>
  )
}

export function PermissionListTab({
  resourceType,
  resourceId,
  context,
  refreshKey = 0,
  pageSize = 50,
  fixedSubjectType = "user",
  onRosterChange,
  onMutationSuccess,
}: PermissionListTabProps) {
  const { t } = useTranslation("permission")
  const [assignees, setAssignees] = useState<PermissionGrantAssignee[]>([])
  const [models, setModels] = useState<GrantablePermissionModel[]>([])
  const [summary, setSummary] = useState<MyResourcePermissions | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [rosterKeyword, setRosterKeyword] = useState("")
  const rosterRevision = useRef(0)
  useEffect(() => {
    const timer = setTimeout(() => setRosterKeyword(searchQuery.trim()), 300)
    return () => clearTimeout(timer)
  }, [searchQuery])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [pendingAssigneeId, setPendingAssigneeId] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    onRosterChange?.(assignees)
  }, [assignees, onRosterChange])

  useEffect(() => {
    setSearchQuery("")
  }, [fixedSubjectType, resourceId])

  useEffect(() => {
    if (!context.can_manage_permission || context.mode !== "CUSTOM") {
      setModels([])
      return
    }
    let cancelled = false
    void getGrantablePermissionModelsApi(resourceType, resourceId)
      .then((result) => {
        if (!cancelled) setModels(result.filter((model) => model.active))
      })
      .catch(() => {
        if (!cancelled) setModels([])
      })
    return () => {
      cancelled = true
    }
  }, [context.can_manage_permission, context.mode, resourceId, resourceType])

  const loadRosterPage = useCallback(
    async (cursor: string | null) => {
      const revision = rosterRevision.current
      const page = await getResourcePermissionGrantsApi(
        resourceType,
        resourceId,
        { cursor, page_size: pageSize, keyword: rosterKeyword, subject_type: fixedSubjectType },
      )
      if (revision !== rosterRevision.current) return
      setAssignees((current) =>
        cursor ? [...current, ...page.data] : page.data,
      )
      setNextCursor(page.next_cursor)
      setHasMore(page.has_more)
    },
    [pageSize, resourceId, resourceType, rosterKeyword, fixedSubjectType],
  )

  useEffect(() => {
    let cancelled = false
    rosterRevision.current += 1
    setLoadingMore(false)
    setAssignees([])
    setSummary(null)
    setNextCursor(null)
    setHasMore(false)
    setFailed(false)
    setLoading(true)

    const request = context.can_manage_permission
      ? getResourcePermissionGrantsApi(resourceType, resourceId, {
          cursor: null,
          page_size: pageSize,
          keyword: rosterKeyword,
          subject_type: fixedSubjectType,
        })
      : getMyResourcePermissionsApi(resourceType, resourceId)

    void request
      .then((result) => {
        if (cancelled) return
        if (context.can_manage_permission) {
          const page = result as Awaited<
            ReturnType<typeof getResourcePermissionGrantsApi>
          >
          setAssignees(page.data)
          setNextCursor(page.next_cursor)
          setHasMore(page.has_more)
        } else {
          setSummary(result as MyResourcePermissions)
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [
    context.can_manage_permission,
    pageSize,
    refreshKey,
    resourceId,
    resourceType,
    rosterKeyword,
    fixedSubjectType,
  ])

  const visibleAssignees = useMemo(() => assignees.filter(
    assignee => assignee.subject.type === fixedSubjectType,
  ), [assignees, fixedSubjectType])

  const mutateAssignee = async (
    assignee: PermissionGrantAssignee,
    change:
      | { op: "MOVE"; target_model_key: string }
      | { op: "REMOVE" },
  ) => {
    if (pendingAssigneeId !== null) return
    setPendingAssigneeId(assignee.assignee_id)
    setFailed(false)
    try {
      const result = await mutateResourceGrantsApi(resourceType, resourceId, {
        idempotency_key: createMutationIdempotencyKey(),
        expected_resource_version: context.resource_version,
        expected_catalog_release_id: context.catalog_release_id,
        changes: [
          change.op === "MOVE"
            ? {
                op: "MOVE",
                assignee_id: assignee.assignee_id,
                expected_assignee_version: assignee.assignee_version,
                target_model_key: change.target_model_key,
              }
            : {
                op: "REMOVE",
                assignee_id: assignee.assignee_id,
                expected_assignee_version: assignee.assignee_version,
              },
        ],
      })
      setAssignees(result.items)
      onMutationSuccess?.(result)
    } catch {
      setFailed(true)
    } finally {
      setPendingAssigneeId(null)
    }
  }

  const handleRemove = (assignee: PermissionGrantAssignee) => {
    bsConfirm({
      desc: t("action.confirmRevoke"),
      onOk(next) {
        void mutateAssignee(assignee, { op: "REMOVE" })
        next()
      },
    })
  }

  const handleLoadMore = async () => {
    if (!nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      await loadRosterPage(nextCursor)
    } catch {
      setFailed(true)
    } finally {
      setLoadingMore(false)
    }
  }

  const searchPlaceholder =
    fixedSubjectType === "user_group"
      ? t("search.userGroup")
      : t(`search.${fixedSubjectType}`)

  if (loading) {
    return (
      <div
        className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground"
        role="status"
      >
        <Loader2 aria-hidden="true" className="size-4 animate-spin" />
        {t("roster.loading")}
      </div>
    )
  }

  if (summary) return <SummaryView summary={summary} />

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative shrink-0">
        <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
        <input
          type="search"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
          className="h-9 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-sm text-[#212121] outline-none transition-colors placeholder:text-[#999999] focus:border-primary focus:ring-2 focus:ring-primary/10"
        />
      </div>

      {failed && (
        <Alert
          type="error"
          className="mt-3"
          description={t("roster.loadFailed")}
          live
        />
      )}

      <div className="mt-3 min-h-0 flex-1 overflow-y-auto">
        {visibleAssignees.map((assignee) => (
          <RosterRow
            key={assignee.assignee_id}
            assignee={assignee}
            context={context}
            models={models}
            pending={pendingAssigneeId === assignee.assignee_id}
            onMove={(item, modelKey) =>
              void mutateAssignee(item, {
                op: "MOVE",
                target_model_key: modelKey,
              })
            }
            onRemove={handleRemove}
          />
        ))}
        {visibleAssignees.length === 0 && (
          <p className="py-10 text-center text-sm text-muted-foreground">
            {searchQuery.trim()
              ? t("empty.searchResults")
              : t("list.emptyForSubject")}
          </p>
        )}
        {hasMore && (
          <Button type="button" variant="outlined" className="mx-auto mt-3 flex min-h-9" disabled={loadingMore} onClick={() => void handleLoadMore()} color="default">
            {loadingMore ? t("roster.loadingMore") : t("roster.loadMore")}
          </Button>
        )}
      </div>
    </div>
  )
}
