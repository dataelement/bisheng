import {
  AlertTriangle,
  Building2,
  Loader2,
  LockKeyhole,
  User,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  getMyResourcePermissions,
  getResourcePermissionGrants,
} from "~/api/permission";
import type {
  MyResourcePermissions,
  PermissionGrantAssignee,
  ResourcePermissionContext,
  ResourceType,
} from "~/api/permission";
import { Button } from "~/components/ui";
import { useLocalize } from "~/hooks";
import { SourceBadge } from "./SourceBadge";

interface PermissionListTabProps {
  resourceType: ResourceType;
  resourceId: string;
  context: ResourcePermissionContext;
  refreshKey?: number;
  pageSize?: number;
  showContextHeader?: boolean;
  onRosterChange?: (assignees: PermissionGrantAssignee[]) => void;
}

const SUBJECT_ICONS = {
  user: User,
  department: Building2,
  user_group: Users,
};

function canEditAssignee(
  assignee: PermissionGrantAssignee,
  context: ResourcePermissionContext,
): boolean {
  return (
    context.mode === "CUSTOM" &&
    assignee.scope === "LOCAL" &&
    assignee.editable &&
    !assignee.protected
  );
}

interface RosterRowProps {
  assignee: PermissionGrantAssignee;
  context: ResourcePermissionContext;
}

function RosterRow({ assignee, context }: RosterRowProps) {
  const localize = useLocalize();
  const SubjectIcon = SUBJECT_ICONS[assignee.subject.type];
  const editable = canEditAssignee(assignee, context);

  return (
    <article
      data-testid={`permission-assignee-${assignee.assignee_id}`}
      data-editable={String(editable)}
      className="grid gap-3 rounded-lg border border-[#EBECF0] bg-white p-4 md:grid-cols-[minmax(0,1fr)_minmax(9rem,0.6fr)_auto]"
    >
      <div className="flex min-w-0 items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-black/[0.04]">
          <SubjectIcon aria-hidden="true" className="size-4 text-[#818181]" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[#212121]">
            {assignee.subject.name ||
              `${assignee.subject.type}:${assignee.subject.id}`}
          </p>
          <p className="truncate text-xs text-[#818181]">
            {assignee.subject.type}:{assignee.subject.id}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <SourceBadge source={assignee.source} />
            <span className="rounded-full bg-black/[0.04] px-2 py-0.5 text-xs text-[#818181]">
              {localize(
                `f048_permission.scope.${assignee.scope.toLowerCase()}`,
              )}
            </span>
            {assignee.protected && (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800">
                <LockKeyhole aria-hidden="true" className="size-3" />
                {localize("f048_permission.roster.protected")}
              </span>
            )}
          </div>
          {assignee.inherited_from && (
            <p className="mt-2 text-xs text-[#818181]">
              {localize("f048_permission.roster.inherited_from")}:{" "}
              {assignee.inherited_from}
            </p>
          )}
        </div>
      </div>

      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-[#212121]">
          {assignee.model.name}
        </p>
        <p className="mt-1 text-xs text-[#818181]">
          {localize("f048_permission.model.level")}:{" "}
          {assignee.model.level ??
            localize("f048_permission.action_level.unassigned")}
        </p>
        {!assignee.model.active && (
          <p className="mt-1 text-xs font-medium text-red-600">
            {localize("f048_permission.model.inactive")}
          </p>
        )}
      </div>

      {!editable && (
        <span className="self-start rounded-full border px-2 py-1 text-xs text-[#818181]">
          {localize("f048_permission.roster.read_only")}
        </span>
      )}
    </article>
  );
}

function SummaryView({ summary }: { summary: MyResourcePermissions }) {
  const localize = useLocalize();

  return (
    <section className="rounded-lg border border-[#EBECF0] bg-black/[0.02] p-4">
      <p className="text-sm font-medium text-[#212121]">
        {localize("f048_permission.roster.summary_only")}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {summary.actions.map((action) => (
          <span
            key={action}
            className="rounded-full bg-blue-500/[0.07] px-2.5 py-1 text-xs font-medium text-blue-500"
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
  );
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
  const localize = useLocalize();
  const [assignees, setAssignees] = useState<PermissionGrantAssignee[]>([]);
  const [summary, setSummary] = useState<MyResourcePermissions | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    onRosterChange?.(assignees);
  }, [assignees, onRosterChange]);

  const loadPage = useCallback(
    async (cursor: string | null) => {
      const page = await getResourcePermissionGrants(
        resourceType,
        resourceId,
        { cursor, page_size: pageSize },
      );
      setAssignees((current) =>
        cursor ? [...current, ...page.data] : page.data,
      );
      setNextCursor(page.next_cursor);
      setHasMore(page.has_more);
    },
    [pageSize, resourceId, resourceType],
  );

  useEffect(() => {
    let cancelled = false;
    setAssignees([]);
    setSummary(null);
    setNextCursor(null);
    setHasMore(false);
    setFailed(false);
    setLoading(true);

    const request = context.can_manage_permission
      ? getResourcePermissionGrants(resourceType, resourceId, {
          cursor: null,
          page_size: pageSize,
        })
      : getMyResourcePermissions(resourceType, resourceId);

    void request
      .then((result) => {
        if (cancelled) return;
        if (context.can_manage_permission) {
          const page = result as Awaited<
            ReturnType<typeof getResourcePermissionGrants>
          >;
          setAssignees(page.data);
          setNextCursor(page.next_cursor);
          setHasMore(page.has_more);
        } else {
          setSummary(result as MyResourcePermissions);
        }
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    context.can_manage_permission,
    pageSize,
    refreshKey,
    resourceId,
    resourceType,
  ]);

  const handleLoadMore = async () => {
    if (!nextCursor || loadingMore) return;
    setLoadingMore(true);
    try {
      await loadPage(nextCursor);
    } catch {
      setFailed(true);
    } finally {
      setLoadingMore(false);
    }
  };

  const parent =
    context.parent_type && context.parent_id
      ? `${context.parent_type}:${context.parent_id}`
      : null;

  return (
    <div className="flex min-h-0 flex-col gap-4">
      {showContextHeader && (
        <header className="flex flex-wrap items-center gap-2 rounded-lg border border-[#EBECF0] bg-black/[0.02] px-4 py-3">
          <span className="rounded-full bg-blue-500/[0.07] px-2.5 py-1 text-xs font-medium text-blue-500">
            {localize(
              `f048_permission.mode.${context.mode.toLowerCase()}`,
            )}
          </span>
          {parent && (
            <p className="text-xs text-[#818181]">
              {localize("f048_permission.mode.parent")}: {parent}
            </p>
          )}
        </header>
      )}

      {loading && (
        <div className="flex min-h-32 items-center justify-center gap-2 text-sm text-[#818181]">
          <Loader2 aria-hidden="true" className="size-4 animate-spin" />
          {localize("f048_permission.roster.loading")}
        </div>
      )}

      {!loading && failed && (
        <div
          className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
          role="alert"
        >
          <AlertTriangle aria-hidden="true" className="size-4" />
          {localize("f048_permission.roster.load_failed")}
        </div>
      )}

      {!loading && !failed && summary && <SummaryView summary={summary} />}

      {!loading && !failed && !summary && (
        <div className="flex min-h-0 flex-col gap-3">
          {assignees.map((assignee) => (
            <RosterRow
              key={assignee.assignee_id}
              assignee={assignee}
              context={context}
            />
          ))}
          {assignees.length === 0 && (
            <p className="rounded-lg border border-dashed p-8 text-center text-sm text-[#818181]">
              {localize("f048_permission.roster.empty")}
            </p>
          )}
          {hasMore && (
            <Button
              type="button"
              color="default"
              variant="outlined"
              size="medium"
              disabled={loadingMore}
              onClick={() => void handleLoadMore()}
            >
              {loadingMore
                ? localize("f048_permission.roster.loading_more")
                : localize("f048_permission.roster.load_more")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
