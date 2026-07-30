import { Button } from "@/components/bs-ui/button"
import {
  getMyResourcePermissionsApi,
  getResourcePermissionGrantsApi,
  type MyResourcePermissions,
  type PermissionGrantAssignee,
  type PermissionResourceType,
  type ResourcePermissionContext,
} from "@/controllers/API/permission"
import {
  AlertTriangle,
  Building2,
  Loader2,
  LockKeyhole,
  User,
  Users,
} from "lucide-react"
import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { SourceBadge } from "./SourceBadge"

interface PermissionListTabProps {
  resourceType: PermissionResourceType
  resourceId: string
  context: ResourcePermissionContext
  refreshKey?: number
  pageSize?: number
  showContextHeader?: boolean
  onRosterChange?: (assignees: PermissionGrantAssignee[]) => void
}

const SUBJECT_ICONS = {
  user: User,
  department: Building2,
  user_group: Users,
}

function assigneeEditable(
  assignee: PermissionGrantAssignee,
  context: ResourcePermissionContext,
): boolean {
  return (
    context.mode === "CUSTOM" &&
    assignee.scope === "LOCAL" &&
    assignee.editable &&
    !assignee.protected
  )
}

interface RosterRowProps {
  assignee: PermissionGrantAssignee
  context: ResourcePermissionContext
}

function RosterRow({ assignee, context }: RosterRowProps) {
  const { t } = useTranslation("permission")
  const SubjectIcon = SUBJECT_ICONS[assignee.subject.type]
  const editable = assigneeEditable(assignee, context)

  return (
    <article
      data-testid={`permission-assignee-${assignee.assignee_id}`}
      data-editable={String(editable)}
      className="grid gap-3 rounded-xl border bg-background p-4 md:grid-cols-[minmax(0,1fr)_minmax(9rem,0.6fr)_auto]"
    >
      <div className="flex min-w-0 items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted">
          <SubjectIcon
            aria-hidden="true"
            className="size-4 text-muted-foreground"
          />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">
            {assignee.subject.name ||
              `${assignee.subject.type}:${assignee.subject.id}`}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {assignee.subject.type}:{assignee.subject.id}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <SourceBadge source={assignee.source} />
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {t(`scope.${assignee.scope.toLowerCase()}`)}
            </span>
            {assignee.protected && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-900">
                <LockKeyhole aria-hidden="true" className="size-3" />
                {t("roster.protected")}
              </span>
            )}
          </div>
          {assignee.inherited_from && (
            <p className="mt-2 text-xs text-muted-foreground">
              {t("roster.inheritedFrom")}:{" "}
              <span>{assignee.inherited_from}</span>
            </p>
          )}
        </div>
      </div>

      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">
          {assignee.model.name}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("model.level")}:{" "}
          {assignee.model.level ?? t("actionLevel.unassigned")}
        </p>
        {!assignee.model.active && (
          <p className="mt-1 text-xs font-medium text-red-700">
            {t("model.inactive")}
          </p>
        )}
      </div>

      {!editable && (
        <span className="self-start rounded-full border px-2 py-1 text-xs text-muted-foreground">
          {t("roster.readOnly")}
        </span>
      )}
    </article>
  )
}

interface SummaryViewProps {
  summary: MyResourcePermissions
}

function SummaryView({ summary }: SummaryViewProps) {
  const { t } = useTranslation("permission")

  return (
    <section
      aria-label={t("roster.myPermissions")}
      className="rounded-xl border bg-muted/20 p-4"
    >
      <p className="text-sm font-medium text-foreground">
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
      <div className="mt-3 flex flex-wrap gap-2">
        {summary.sources.map((source, index) => (
          <SourceBadge
            key={`${source.type}-${String(source.include_children)}-${index}`}
            source={source}
          />
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
  showContextHeader = true,
  onRosterChange,
}: PermissionListTabProps) {
  const { t } = useTranslation("permission")
  const [assignees, setAssignees] = useState<PermissionGrantAssignee[]>([])
  const [summary, setSummary] = useState<MyResourcePermissions | null>(null)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    onRosterChange?.(assignees)
  }, [assignees, onRosterChange])

  const loadRosterPage = useCallback(
    async (cursor: string | null) => {
      const page = await getResourcePermissionGrantsApi(
        resourceType,
        resourceId,
        { cursor, page_size: pageSize },
      )
      setAssignees((current) =>
        cursor ? [...current, ...page.data] : page.data,
      )
      setNextCursor(page.next_cursor)
      setHasMore(page.has_more)
    },
    [pageSize, resourceId, resourceType],
  )

  useEffect(() => {
    let cancelled = false
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
  ])

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

  const parent =
    context.parent_type && context.parent_id
      ? `${context.parent_type}:${context.parent_id}`
      : null

  return (
    <div className="flex min-h-0 flex-col gap-4">
      {showContextHeader && (
        <header className="flex flex-wrap items-center gap-2 rounded-xl border bg-muted/20 px-4 py-3">
          <span className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
            {t(`mode.${context.mode.toLowerCase()}`)}
          </span>
          {parent && (
            <p className="text-xs text-muted-foreground">
              {t("mode.parent")}: <span>{parent}</span>
            </p>
          )}
        </header>
      )}

      {loading && (
        <div
          className="flex min-h-40 items-center justify-center gap-2 text-sm text-muted-foreground"
          role="status"
        >
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          {t("roster.loading")}
        </div>
      )}

      {failed && !loading && (
        <p
          className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-900"
          role="alert"
        >
          <AlertTriangle aria-hidden="true" className="size-4" />
          {t("roster.loadFailed")}
        </p>
      )}

      {!loading && !failed && summary && <SummaryView summary={summary} />}

      {!loading && !failed && context.can_manage_permission && (
        <>
          <div className="flex flex-col gap-2">
            {assignees.map((assignee) => (
              <RosterRow
                key={assignee.assignee_id}
                assignee={assignee}
                context={context}
              />
            ))}
            {assignees.length === 0 && (
              <p className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
                {t("roster.empty")}
              </p>
            )}
          </div>
          {hasMore && (
            <Button
              type="button"
              variant="outline"
              className="min-h-11 self-center"
              disabled={loadingMore}
              onClick={() => void handleLoadMore()}
            >
              {loadingMore ? t("roster.loadingMore") : t("roster.loadMore")}
            </Button>
          )}
        </>
      )}
    </div>
  )
}
