import { Outlined } from "bisheng-icons";
import {
  AlertTriangle,
  Building2,
  Loader2,
  LockKeyhole,
  Search,
  Trash2,
  User,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getGrantablePermissionModels,
  getMyResourcePermissions,
  getResourcePermissionGrants,
  mutateResourceGrants,
} from "~/api/permission";
import type {
  GrantablePermissionModel,
  MutateResourceGrantsResult,
  MyResourcePermissions,
  PermissionGrantAssignee,
  ResourcePermissionContext,
  ResourceType,
  SubjectType,
} from "~/api/permission";
import { Button } from "~/components/ui";
import { useLocalize } from "~/hooks";
import { useConfirm } from "~/Providers";
import { SourceBadge } from "./SourceBadge";

interface PermissionListTabProps {
  resourceType: ResourceType;
  resourceId: string;
  context: ResourcePermissionContext;
  refreshKey?: number;
  pageSize?: number;
  fixedSubjectType?: SubjectType;
  onRosterChange?: (assignees: PermissionGrantAssignee[]) => void;
  onMutationSuccess?: (result: MutateResourceGrantsResult) => void;
}

const SUBJECT_ICONS = {
  user: User,
  department: Building2,
  user_group: Users,
};

function createMutationIdempotencyKey(): string {
  return `grant-mutate-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

function canEditAssignee(
  assignee: PermissionGrantAssignee,
  context: ResourcePermissionContext,
): boolean {
  return (
    context.mode === "CUSTOM" &&
    context.can_manage_permission &&
    assignee.scope === "LOCAL" &&
    assignee.editable &&
    !assignee.protected
  );
}

function getAvatarLabel(assignee: PermissionGrantAssignee): string {
  const name = assignee.subject.name?.trim() || assignee.subject.id;
  return (name.charAt(0) || "U").toUpperCase();
}

interface RosterRowProps {
  assignee: PermissionGrantAssignee;
  context: ResourcePermissionContext;
  models: GrantablePermissionModel[];
  pending: boolean;
  onMove: (assignee: PermissionGrantAssignee, modelKey: string) => void;
  onRemove: (assignee: PermissionGrantAssignee) => void;
}

function RosterRow({
  assignee,
  context,
  models,
  pending,
  onMove,
  onRemove,
}: RosterRowProps) {
  const localize = useLocalize();
  const SubjectIcon = SUBJECT_ICONS[assignee.subject.type];
  const editable = canEditAssignee(assignee, context);
  const displayName =
    assignee.subject.name ||
    `${assignee.subject.type}:${assignee.subject.id}`;
  const currentIsGrantable = models.some(
    (model) => model.key === assignee.model.key,
  );

  return (
    <article
      data-testid={`permission-assignee-${assignee.assignee_id}`}
      data-editable={String(editable)}
      className="flex min-h-[58px] items-center gap-4 border-b border-[#F2F3F5] py-3 last:border-b-0"
    >
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {assignee.subject.type === "user" ? (
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-[#C9CDD4] text-sm font-semibold text-white">
            {getAvatarLabel(assignee)}
          </span>
        ) : (
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-blue-500/[0.07] text-blue-500">
            <SubjectIcon aria-hidden="true" className="size-4" />
          </span>
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-[#212121]">
            {displayName}
          </p>
          <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-1 text-xs text-[#86909C]">
            <SourceBadge source={assignee.source} />
            <span>
              {localize(
                `f048_permission.scope.${assignee.scope.toLowerCase()}`,
              )}
            </span>
            {assignee.inherited_from && (
              <span className="truncate">
                · {localize("f048_permission.roster.inherited_from")}: {" "}
                {assignee.inherited_from}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="flex w-[176px] shrink-0 items-center justify-end gap-1 max-[560px]:w-[132px]">
        {editable ? (
          <>
            {/* The native select arrow is painted over right-aligned text, so hide it and
                reserve room for our own chevron. */}
            <div className="relative flex min-w-0 flex-1 items-center">
              <select
                aria-label={`grant.model.${assignee.assignee_id}`}
                value={assignee.model.key}
                disabled={pending}
                onChange={(event) => onMove(assignee, event.target.value)}
                className="h-8 w-full min-w-0 cursor-pointer appearance-none rounded-md border-0 bg-transparent pl-2 pr-6 text-right text-sm text-[#4E5969] outline-none hover:bg-black/[0.03] focus-visible:ring-2 focus-visible:ring-blue-500/40 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {!currentIsGrantable && (
                  <option value={assignee.model.key}>
                    {assignee.model.name}
                  </option>
                )}
                {models.map((model) => (
                  <option key={model.key} value={model.key}>
                    {model.name}
                  </option>
                ))}
              </select>
              <Outlined.Down
                aria-hidden="true"
                className="pointer-events-none absolute right-1.5 size-3.5 text-[#86909C]"
              />
            </div>
            <button
              type="button"
              aria-label={`${localize("f048_permission.grant.remove")}.${
                assignee.assignee_id
              }`}
              disabled={pending}
              className="flex size-8 shrink-0 items-center justify-center rounded-md text-[#86909C] transition-colors hover:bg-red-50 hover:text-red-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300 disabled:cursor-not-allowed disabled:opacity-50"
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
                aria-label={localize("f048_permission.roster.protected")}
                className="size-3.5 shrink-0"
              />
            )}
          </span>
        )}
      </div>
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
    </section>
  );
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
  const localize = useLocalize();
  const confirm = useConfirm();
  const [assignees, setAssignees] = useState<PermissionGrantAssignee[]>([]);
  const [models, setModels] = useState<GrantablePermissionModel[]>([]);
  const [summary, setSummary] = useState<MyResourcePermissions | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [pendingAssigneeId, setPendingAssigneeId] = useState<string | null>(
    null,
  );
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    onRosterChange?.(assignees);
  }, [assignees, onRosterChange]);

  useEffect(() => {
    setSearchQuery("");
  }, [fixedSubjectType, resourceId]);

  useEffect(() => {
    if (!context.can_manage_permission || context.mode !== "CUSTOM") {
      setModels([]);
      return;
    }
    let cancelled = false;
    void getGrantablePermissionModels(resourceType, resourceId)
      .then((result) => {
        if (!cancelled) setModels(result.filter((model) => model.active));
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [context.can_manage_permission, context.mode, resourceId, resourceType]);

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

  const visibleAssignees = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return assignees.filter((assignee) => {
      if (assignee.subject.type !== fixedSubjectType) return false;
      if (!query) return true;
      return [
        assignee.subject.name,
        assignee.subject.id,
        assignee.model.name,
        assignee.source.type,
        assignee.inherited_from,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(query);
    });
  }, [assignees, fixedSubjectType, searchQuery]);

  const mutateAssignee = async (
    assignee: PermissionGrantAssignee,
    change:
      | { op: "MOVE"; target_model_key: string }
      | { op: "REMOVE" },
  ) => {
    if (pendingAssigneeId !== null) return;
    setPendingAssigneeId(assignee.assignee_id);
    setFailed(false);
    try {
      const result = await mutateResourceGrants(resourceType, resourceId, {
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
      });
      setAssignees(result.items);
      onMutationSuccess?.(result);
    } catch {
      setFailed(true);
    } finally {
      setPendingAssigneeId(null);
    }
  };

  const handleRemove = async (assignee: PermissionGrantAssignee) => {
    const confirmed = await confirm({
      variant: "destructive",
      title: localize("com_permission.confirm_revoke"),
      description: assignee.subject.name || assignee.subject.id,
      confirmText: localize("com_permission.action_revoke"),
    });
    if (!confirmed) return;
    await mutateAssignee(assignee, { op: "REMOVE" });
  };

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

  const searchPlaceholder = localize(
    fixedSubjectType === "user_group"
      ? "com_permission.search_user_group"
      : `com_permission.search_${fixedSubjectType}`,
  );

  if (loading) {
    return (
      <div
        className="flex min-h-40 items-center justify-center gap-2 text-sm text-[#818181]"
        role="status"
      >
        <Loader2 aria-hidden="true" className="size-4 animate-spin" />
        {localize("f048_permission.roster.loading")}
      </div>
    );
  }

  if (summary) return <SummaryView summary={summary} />;

  return (
    <>
      <div className="flex h-full min-h-0 flex-col">
        <div className="relative shrink-0">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="h-9 w-full rounded-md border border-[#EBECF0] bg-white pl-9 pr-3 text-sm text-[#212121] outline-none transition-colors placeholder:text-[#999999] focus:border-blue-500 focus:ring-2 focus:ring-blue-500/10"
          />
        </div>

        {failed && (
          <div
            className="mt-3 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
            role="alert"
          >
            <AlertTriangle aria-hidden="true" className="size-4" />
            {localize("f048_permission.roster.load_failed")}
          </div>
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
              onRemove={(item) => void handleRemove(item)}
            />
          ))}
          {visibleAssignees.length === 0 && (
            <p className="py-10 text-center text-sm text-[#818181]">
              {searchQuery.trim()
                ? localize("com_permission.empty_search")
                : localize("com_permission.list_empty_for_subject")}
            </p>
          )}
          {hasMore && (
            <Button
              type="button"
              color="default"
              variant="outlined"
              size="medium"
              className="mx-auto mt-3 flex"
              disabled={loadingMore}
              onClick={() => void handleLoadMore()}
            >
              {loadingMore
                ? localize("f048_permission.roster.loading_more")
                : localize("f048_permission.roster.load_more")}
            </Button>
          )}
        </div>
      </div>
    </>
  );
}
