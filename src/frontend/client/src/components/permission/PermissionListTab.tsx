import { useToastContext, useConfirm } from "~/Providers";
import {
  authorizeResource,
  getGrantableRelationModels,
  getResourceGrantDepartments,
  getResourcePermissions,
} from "~/api/permission";
import type {
  PermissionEntry,
  RelationLevel,
  ResourceType,
  RelationModel,
  RevokeItem,
} from "~/api/permission";
import { Avatar, AvatarName } from "~/components/ui/Avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { Building2, ChevronDown, Loader2, RotateCcw, Search, Trash2, User, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { buildDepartmentPathLabelMap } from "./departmentPathUtils";
import { RelationModelOption } from "./RelationSelect";

const SUBJECT_ICONS = {
  user: User,
  department: Building2,
  user_group: Users,
};

const LIST_SUBJECT_TYPES = ["user", "department", "user_group"] as const;
type ListSubjectType = (typeof LIST_SUBJECT_TYPES)[number];

interface PermissionListTabProps {
  resourceType: ResourceType;
  resourceId: string;
  refreshKey: number;
  prefetchedGrantableModels?: RelationModel[];
  prefetchedGrantableModelsLoaded?: boolean;
  prefetchedUseDefaultModels?: boolean;
  skipGrantableModelsRequest?: boolean;
  // UI-only: when provided, hides the internal subject type switcher
  // and locks the list to the given subject type.
  fixedSubjectType?: ListSubjectType;
}

const DEFAULT_MODELS: RelationModelOption[] = [
  { id: "owner", name: "所有者", relation: "owner" },
  { id: "manager", name: "可管理", relation: "manager" },
  { id: "editor", name: "可编辑", relation: "editor" },
  { id: "viewer", name: "可查看", relation: "viewer" },
];

export function PermissionListTab({
  resourceType,
  resourceId,
  refreshKey,
  prefetchedGrantableModels,
  prefetchedGrantableModelsLoaded = false,
  prefetchedUseDefaultModels = false,
  skipGrantableModelsRequest = false,
  fixedSubjectType,
}: PermissionListTabProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const confirm = useConfirm();
  const [entries, setEntries] = useState<PermissionEntry[]>([]);
  const [listTab, setListTab] = useState<ListSubjectType>(fixedSubjectType ?? "user");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [grantableModels, setGrantableModels] = useState<RelationModel[]>(
    prefetchedGrantableModels || [],
  );
  const [useDefaultModels, setUseDefaultModels] = useState(prefetchedUseDefaultModels);
  const [deptPathById, setDeptPathById] = useState<Map<number, string>>(() => new Map());
  const [userSelectedTab, setUserSelectedTab] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isListScrolling, setIsListScrolling] = useState(false);
  const listScrollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getResourceGrantDepartments(resourceType, resourceId, { signal: controller.signal })
      .then((res) => {
        if (!controller.signal.aborted && Array.isArray(res)) {
          setDeptPathById(buildDepartmentPathLabelMap(res));
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setDeptPathById(new Map());
        }
      });
    return () => controller.abort();
  }, [refreshKey, resourceId, resourceType]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const res = await getResourcePermissions(resourceType, resourceId);
      if (res) setEntries(res);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [resourceType, resourceId]);

  useEffect(() => {
    loadData();
  }, [loadData, refreshKey]);

  useEffect(() => {
    setListTab(fixedSubjectType ?? "user");
    setUserSelectedTab(false);
    setSearchQuery("");
  }, [resourceId, fixedSubjectType]);

  useEffect(() => {
    return () => {
      if (listScrollTimerRef.current) clearTimeout(listScrollTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (skipGrantableModelsRequest) {
      if (!prefetchedGrantableModelsLoaded) return;
      setGrantableModels(prefetchedGrantableModels || []);
      setUseDefaultModels(prefetchedUseDefaultModels);
      return;
    }

    getGrantableRelationModels(resourceType, resourceId)
      .then((res) => {
        setUseDefaultModels(false);
        setGrantableModels(Array.isArray(res) ? res : []);
      })
      .catch(() => {
        setUseDefaultModels(false);
        setGrantableModels([]);
      });
  }, [
    prefetchedGrantableModels,
    prefetchedGrantableModelsLoaded,
    prefetchedUseDefaultModels,
    refreshKey,
    resourceId,
    resourceType,
    skipGrantableModelsRequest,
  ]);

  const grantableModelOptions = useMemo<RelationModelOption[]>(() => {
    if (useDefaultModels) return DEFAULT_MODELS;

    return (grantableModels || []).map((m) => ({
      id: m.id,
      name: m.is_system ? localize(`com_permission.level_${m.relation}`) : m.name,
      relation: m.relation as RelationLevel,
    }));
  }, [grantableModels, localize, useDefaultModels]);

  const displayModels = useMemo<RelationModelOption[]>(() => {
    const opts = [...grantableModelOptions];
    const ids = new Set(opts.map((o) => o.id));
    for (const entry of entries) {
      if (!entry.model_id || ids.has(entry.model_id)) continue;
      ids.add(entry.model_id);
      opts.push({
        id: entry.model_id,
        name: entry.model_name || entry.relation,
        relation: entry.relation as RelationLevel,
      });
    }
    return opts.length ? opts : DEFAULT_MODELS;
  }, [entries, grantableModelOptions]);

  const subjectEntries = useMemo(
    () => entries.filter((entry) => entry.subject_type === listTab),
    [entries, listTab],
  );
  const ownerEntryCount = useMemo(
    () => entries.filter((entry) => entry.subject_type === "user" && entry.relation === "owner").length,
    [entries],
  );

  useEffect(() => {
    if (fixedSubjectType || userSelectedTab || entries.length === 0 || subjectEntries.length > 0) return;
    const firstNonEmptyTab = LIST_SUBJECT_TYPES.find((subjectType) =>
      entries.some((entry) => entry.subject_type === subjectType),
    );
    if (firstNonEmptyTab) setListTab(firstNonEmptyTab);
  }, [entries, fixedSubjectType, subjectEntries.length, userSelectedTab]);

  const normalizedSearchQuery = searchQuery.trim().toLowerCase();

  const getEntryDisplayName = useCallback(
    (entry: PermissionEntry) => {
      if (entry.subject_type === "department") {
        return deptPathById.get(entry.subject_id)
          ?? entry.subject_name
          ?? `${entry.subject_type}:${entry.subject_id}`;
      }
      return entry.subject_name ?? `${entry.subject_type}:${entry.subject_id}`;
    },
    [deptPathById],
  );

  const visibleEntries = useMemo(() => {
    if (!normalizedSearchQuery) {
      return subjectEntries;
    }

    return subjectEntries.filter((entry) => {
      const name = getEntryDisplayName(entry);
      const groupNames = entry.subject_group_names?.join(" ") ?? "";
      const memberNames = entry.subject_member_names?.join(" ") ?? "";
      const includeChildrenText =
        entry.subject_type === "department" && entry.include_children
          ? localize("com_permission.include_children")
          : "";
      return `${name} ${groupNames} ${memberNames} ${includeChildrenText}`
        .toLowerCase()
        .includes(normalizedSearchQuery);
    });
  }, [getEntryDisplayName, localize, normalizedSearchQuery, subjectEntries]);

  const handleModify = async (entry: PermissionEntry, modelId: string) => {
    const model = grantableModelOptions.find((item) => item.id === modelId);
    const newLevel = (model?.relation || "viewer") as RelationLevel;
    if (newLevel === entry.relation && (entry.model_id || entry.relation) === modelId) return;
    try {
      await authorizeResource(
        resourceType,
        resourceId,
        [
          {
            subject_type: entry.subject_type,
            subject_id: entry.subject_id,
            relation: newLevel,
            model_id: modelId,
            ...(entry.subject_type === "department"
              ? { include_children: Boolean(entry.include_children) }
              : {}),
          },
        ],
        [
          {
            subject_type: entry.subject_type,
            subject_id: entry.subject_id,
            relation: entry.relation,
            ...(entry.subject_type === "department"
              ? { include_children: Boolean(entry.include_children) }
              : {}),
          },
        ],
      );
      showToast({ message: localize("com_permission.success_modify"), status: "success" });
      loadData();
    } catch {
      showToast({
        message: entry.relation === "owner"
          ? localize("com_permission.error_last_owner")
          : localize("com_permission.error_revoke_failed"),
        status: "error",
      });
    }
  };

  const getSubjectEntries = useCallback(
    (entry: PermissionEntry) =>
      entries.filter(
        (candidate) =>
          candidate.subject_type === entry.subject_type &&
          candidate.subject_id === entry.subject_id,
      ),
    [entries],
  );

  const canManageEntry = useCallback(
    (entry: PermissionEntry) => {
      const currentModelId = entry.model_id || entry.relation;
      return grantableModelOptions.some((model) => model.id === currentModelId);
    },
    [grantableModelOptions],
  );

  const canDeleteSubject = useCallback(
    (entry: PermissionEntry) => {
      if (!canManageEntry(entry)) return false;
      const relatedEntries = getSubjectEntries(entry);
      if (relatedEntries.some((candidate) => !canManageEntry(candidate))) return false;
      const subjectOwnerCount = relatedEntries.filter(
        (candidate) => candidate.subject_type === "user" && candidate.relation === "owner",
      ).length;
      return subjectOwnerCount === 0 || ownerEntryCount > subjectOwnerCount;
    },
    [canManageEntry, getSubjectEntries, ownerEntryCount],
  );

  const buildRevokeItemsForSubject = (entry: PermissionEntry): RevokeItem[] => {
    const seen = new Set<string>();
    return getSubjectEntries(entry).reduce<RevokeItem[]>((items, candidate) => {
      const includeChildrenValues =
        candidate.subject_type === "department"
          ? (candidate.include_children ? [true, false] : [false])
          : [undefined];

      for (const includeChildren of includeChildrenValues) {
        const key = [
          candidate.subject_type,
          candidate.subject_id,
          candidate.relation,
          includeChildren === undefined ? "" : String(includeChildren),
        ].join(":");
        if (seen.has(key)) {
          continue;
        }
        seen.add(key);
        items.push({
          subject_type: candidate.subject_type,
          subject_id: candidate.subject_id,
          relation: candidate.relation,
          ...(candidate.subject_type === "department"
            ? { include_children: includeChildren }
            : {}),
        });
      }
      return items;
    }, []);
  };

  const handleDeleteSubject = async (entry: PermissionEntry) => {
    const ok = await confirm({
      title: localize("com_permission.action_revoke"),
      description: localize("com_permission.confirm_revoke"),
      confirmText: localize("com_permission.action_revoke"),
      cancelText: localize("com_ui_cancel"),
    });
    if (!ok) return;
    const revokes = buildRevokeItemsForSubject(entry);
    if (revokes.length === 0) return;
    try {
      await authorizeResource(
        resourceType,
        resourceId,
        [],
        revokes,
      );
      showToast({ message: localize("com_permission.success_revoke"), status: "success" });
      loadData();
    } catch {
      showToast({
        message: entry.relation === "owner"
          ? localize("com_permission.error_last_owner")
          : localize("com_permission.error_revoke_failed"),
        status: "error",
      });
    }
  };

  const subjectLabel = (type: ListSubjectType) => {
    const map: Record<ListSubjectType, string> = {
      user: localize("com_permission.subject_user"),
      department: localize("com_permission.subject_department"),
      user_group: localize("com_permission.subject_user_group"),
    };
    return map[type];
  };

  const getPermissionLabel = (entry: PermissionEntry) => {
    const currentModelId = entry.model_id || entry.relation;
    return (
      displayModels.find((item) => item.id === currentModelId)?.name ||
      entry.model_name ||
      localize(`com_permission.level_${entry.relation}`)
    );
  };

  const getSearchPlaceholder = (type: ListSubjectType) => {
    const map: Record<ListSubjectType, string> = {
      user:
        localize("com_subscription.search_user_placeholder") ||
        localize("com_permission.search_user"),
      department: localize("com_permission.search_department"),
      user_group: localize("com_permission.search_user_group"),
    };
    return map[type];
  };

  const getEntryCaption = (entry: PermissionEntry) => {
    if (entry.subject_type === "user") {
      return entry.subject_group_names?.join("、") ?? "";
    }

    if (entry.subject_type === "department") {
      return entry.include_children
        ? `${localize("com_permission.subject_department")} · ${localize("com_permission.include_children")}`
        : localize("com_permission.subject_department");
    }

    return entry.subject_member_names?.join("、") ?? localize("com_permission.subject_user_group");
  };

  const handleListScroll = () => {
    setIsListScrolling(true);
    if (listScrollTimerRef.current) clearTimeout(listScrollTimerRef.current);
    listScrollTimerRef.current = setTimeout(() => setIsListScrolling(false), 500);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-12">
        <span className="text-sm text-gray-500">{localize("com_permission.error_permission_denied")}</span>
        <button
          className="flex items-center gap-1 text-sm text-blue-600 hover:underline"
          onClick={loadData}
        >
          <RotateCcw className="h-3.5 w-3.5" /> {localize("com_ui_retry")}
        </button>
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-gray-500">
        {localize("com_permission.empty_permissions")}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {!fixedSubjectType && (
        <div className="flex w-fit shrink-0 gap-1 rounded-md bg-gray-100 p-1">
          {LIST_SUBJECT_TYPES.map((subjectType) => (
            <button
              key={subjectType}
              type="button"
              className={`rounded px-3 py-1.5 text-sm transition-colors ${
                listTab === subjectType
                  ? "bg-white text-gray-900 shadow"
                  : "text-gray-500 hover:text-gray-700"
              }`}
              onClick={() => {
                setUserSelectedTab(true);
                setListTab(subjectType);
                setSearchQuery("");
              }}
            >
              {subjectLabel(subjectType)}
            </button>
          ))}
        </div>
      )}

      <div className={cn("flex min-h-0 flex-1 flex-col gap-3", !fixedSubjectType && "mt-4")}>
        <div className="relative shrink-0">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#999999]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder={getSearchPlaceholder(listTab)}
            className="h-8 w-full rounded-[6px] border border-[#EBECF0] bg-white pl-9 pr-3 text-[14px] text-[#212121] outline-none transition-colors placeholder:text-[#999999] focus:border-[#C9CDD4]"
          />
        </div>

        <div
          className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto scroll-on-scroll"
          onScroll={handleListScroll}
          data-scrolling={isListScrolling ? "true" : "false"}
        >
          {visibleEntries.length === 0 ? (
            <div className="py-10 text-center text-sm text-gray-500">
              {normalizedSearchQuery && listTab === "user"
                ? localize("com_permission.empty_search")
                : localize("com_permission.list_empty_for_subject")}
            </div>
          ) : (
            <div className="flex flex-col">
              {visibleEntries.map((entry, index) => {
                const Icon = SUBJECT_ICONS[entry.subject_type] || User;
                const currentModelId = entry.model_id || entry.relation;
                const isOwner = entry.relation === "owner";
                const canManageOwnerEntry = isOwner && ownerEntryCount > 1;
                const canModifyEntry = canManageEntry(entry) && grantableModelOptions.length > 0;
                const canDeleteEntrySubject = canDeleteSubject(entry);
                const displayName = getEntryDisplayName(entry);
                const entryCaption = getEntryCaption(entry);

                return (
                  <div
                    key={`${entry.subject_type}-${entry.subject_id}-${index}`}
                    className="flex items-center gap-4 border-b border-[#F2F3F5] py-3 last:border-b-0"
                  >
                    <div className="flex w-[200px] shrink-0 items-center gap-2">
                      {entry.subject_type === "user" ? (
                        <Avatar className="h-8 w-8">
                          <AvatarName
                            name={displayName}
                            className="text-[14px] font-bold leading-[14px]"
                          />
                        </Avatar>
                      ) : (
                        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#EEF2FF] text-[#335CFF]">
                          <Icon className="h-4 w-4" />
                        </span>
                      )}
                      <span className="truncate text-[14px] leading-[22px] text-[#212121]">
                        {displayName}
                      </span>
                    </div>

                    <p className="min-w-0 flex-1 truncate text-[12px] leading-5 text-[#999999]">
                      {entryCaption}
                    </p>

                    <div className="flex w-[136px] shrink-0 items-center justify-end gap-1">
                      {canModifyEntry && (!isOwner || canManageOwnerEntry) ? (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              className="inline-flex h-8 w-[96px] items-center justify-end gap-1 rounded-[6px] px-2 text-[14px] leading-[22px] text-[#999999] transition-colors hover:bg-[#F7F7F7]"
                            >
                              <span className="truncate">{getPermissionLabel(entry)}</span>
                              <ChevronDown className="size-3.5 shrink-0 text-[#999999]" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent
                            align="end"
                            className="z-[120] max-h-[240px] w-[100px] overflow-x-hidden overflow-y-auto rounded-[8px] border border-[#EBECF0] bg-white p-1 shadow-[0px_6px_20px_0px_rgba(117,145,212,0.12)]"
                          >
                            {grantableModelOptions.map((model) => {
                              const active = model.id === currentModelId;
                              return (
                                <DropdownMenuItem
                                  key={model.id}
                                  className={cn(
                                    "rounded-[6px] px-2 py-[5px] text-[14px] leading-[22px]",
                                    active
                                      ? "bg-[#E6EDFC] text-[#335CFF] data-[highlighted]:bg-[#E6EDFC] data-[highlighted]:text-[#335CFF]"
                                      : "text-[#212121] data-[highlighted]:bg-[#F7F7F7] data-[highlighted]:text-[#212121]",
                                  )}
                                  onSelect={() => {
                                    void handleModify(entry, model.id);
                                  }}
                                >
                                  {model.name}
                                </DropdownMenuItem>
                              );
                            })}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      ) : (
                        <span className="truncate text-[14px] leading-[22px] text-[#999999]">
                          {getPermissionLabel(entry)}
                        </span>
                      )}
                      {canDeleteEntrySubject && (
                        <button
                          type="button"
                          aria-label={localize("com_permission.remove")}
                          title={localize("com_permission.remove")}
                          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[6px] text-[#999999] transition-colors hover:bg-[#FFF2F0] hover:text-[#F53F3F]"
                          onClick={() => {
                            void handleDeleteSubject(entry);
                          }}
                        >
                          <Trash2 className="size-4" />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
