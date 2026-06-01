import { Button } from "~/components/ui/Button";
import { Checkbox } from "~/components/ui/Checkbox";
import { useToastContext } from "~/Providers";
import {
  authorizeResource,
  getGrantableRelationModels,
  getResourceGrantDepartments,
  getResourceGrantUserGroups,
  getResourceGrantUsers,
  getResourcePermissions,
} from "~/api/permission";
import type {
  GrantItem,
  PermissionEntry,
  RelationLevel,
  RelationModel,
  ResourceType,
  SelectedSubject,
  SubjectType,
} from "~/api/permission";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { RelationModelOption, RelationSelect } from "./RelationSelect";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";
import { SubjectSearchUser } from "./SubjectSearchUser";
import { SubjectSearchUserGroup } from "./SubjectSearchUserGroup";

const SUBJECT_TYPES: SubjectType[] = ["user", "department", "user_group"];
const DEFAULT_MODELS: RelationModelOption[] = [
  { id: "owner", name: "所有者", relation: "owner" },
  { id: "viewer", name: "可查看", relation: "viewer" },
  { id: "editor", name: "可编辑", relation: "editor" },
  { id: "manager", name: "可管理", relation: "manager" },
];
const EMPTY_GRANTED_SUBJECT_IDS: Record<SubjectType, number[]> = {
  user: [],
  department: [],
  user_group: [],
};

export interface PermissionGrantApiAdapter {
  getPermissions: typeof getResourcePermissions;
  authorize: typeof authorizeResource;
  getGrantableRelationModels: typeof getGrantableRelationModels;
  getGrantUsers?: typeof getResourceGrantUsers;
  getGrantDepartments?: typeof getResourceGrantDepartments;
  getGrantUserGroups?: typeof getResourceGrantUserGroups;
}

// Render selected subjects as chips. Horizontally scrollable with a right-edge fade when overflow occurs.
function SelectedSubjectChips({ subjects, fullText }: { subjects: SelectedSubject[]; fullText: string }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [hasLeftOverflow, setHasLeftOverflow] = useState(false);
  const [hasRightOverflow, setHasRightOverflow] = useState(false);

  const updateOverflow = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setHasLeftOverflow(el.scrollLeft > 1);
    setHasRightOverflow(el.scrollWidth - el.clientWidth - el.scrollLeft > 1);
  }, []);

  useEffect(() => {
    updateOverflow();
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(updateOverflow);
    ro.observe(el);
    return () => ro.disconnect();
  }, [subjects, updateOverflow]);

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setOpen(false);
      return;
    }
    const el = ref.current;
    if (el && el.scrollWidth > el.clientWidth) {
      setOpen(true);
    }
  };

  if (subjects.length === 0) return null;

  return (
    <Tooltip open={open} onOpenChange={handleOpenChange}>
      <TooltipTrigger asChild>
        <div
          ref={ref}
          onScroll={updateOverflow}
          className="min-w-0 flex flex-1 items-center gap-1 overflow-x-auto scrollbar-hide"
          style={(() => {
            if (!hasLeftOverflow && !hasRightOverflow) return undefined;
            const leftStop = hasLeftOverflow ? "24px" : "0";
            const rightStop = hasRightOverflow ? "calc(100% - 24px)" : "100%";
            const value = `linear-gradient(to right, transparent, black ${leftStop}, black ${rightStop}, transparent)`;
            return { maskImage: value, WebkitMaskImage: value };
          })()}
        >
          {subjects.map((subject) => (
            <span
              key={subject.id}
              className="inline-flex shrink-0 items-center rounded-[4px] bg-[#F2F3F5] px-2 py-0.5 text-[14px] leading-[22px] text-[#4E5969]"
            >
              {subject.name}
            </span>
          ))}
        </div>
      </TooltipTrigger>
      <TooltipContent side="top" className="z-[120] max-w-xs break-all">
        {fullText}
      </TooltipContent>
    </Tooltip>
  );
}

interface PermissionGrantTabProps {
  resourceType: ResourceType;
  resourceId: string;
  onSuccess: () => void;
  prefetchedGrantableModels?: RelationModel[];
  prefetchedGrantableModelsLoaded?: boolean;
  prefetchedUseDefaultModels?: boolean;
  skipGrantableModelsRequest?: boolean;
  // UI-only: when provided, hides the internal subject type switcher
  // and locks the grant form to the given subject type.
  fixedSubjectType?: SubjectType;
  includeChildren?: boolean;
  onIncludeChildrenChange?: (value: boolean) => void;
  hideDepartmentIncludeChildrenControl?: boolean;
  permissionApi?: PermissionGrantApiAdapter;
}

const DEFAULT_PERMISSION_API: PermissionGrantApiAdapter = {
  getPermissions: getResourcePermissions,
  authorize: authorizeResource,
  getGrantableRelationModels,
  getGrantUsers: getResourceGrantUsers,
  getGrantDepartments: getResourceGrantDepartments,
  getGrantUserGroups: getResourceGrantUserGroups,
};

export function PermissionGrantTab({
  resourceType,
  resourceId,
  onSuccess,
  prefetchedGrantableModels,
  prefetchedGrantableModelsLoaded = false,
  prefetchedUseDefaultModels = false,
  skipGrantableModelsRequest = false,
  fixedSubjectType,
  includeChildren: includeChildrenProp,
  onIncludeChildrenChange,
  hideDepartmentIncludeChildrenControl = false,
  permissionApi,
}: PermissionGrantTabProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const activePermissionApi = permissionApi ?? DEFAULT_PERMISSION_API;
  const [subjectType, setSubjectType] = useState<SubjectType>(fixedSubjectType ?? "user");
  const [selected, setSelected] = useState<SelectedSubject[]>([]);
  const [models, setModels] = useState<RelationModelOption[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string>("viewer");
  const [internalIncludeChildren, setInternalIncludeChildren] = useState(true);
  const [selectedDepartmentSummary, setSelectedDepartmentSummary] = useState<SelectedSubject[]>([]);
  const [grantedSubjectIds, setGrantedSubjectIds] = useState<Record<SubjectType, number[]>>(
    EMPTY_GRANTED_SUBJECT_IDS
  );
  const [submitting, setSubmitting] = useState(false);
  const includeChildren = includeChildrenProp ?? internalIncludeChildren;
  const handleIncludeChildrenChange = onIncludeChildrenChange ?? setInternalIncludeChildren;

  const applyRelationModels = useCallback((
    relationModels: RelationModel[] | undefined,
    fallbackToDefault: boolean,
  ) => {
    const options: RelationModelOption[] = fallbackToDefault
      ? DEFAULT_MODELS.map((model) => ({
        ...model,
        name: localize(`com_permission.level_${model.relation}`),
      }))
      : (Array.isArray(relationModels) ? relationModels : []).map((m) => ({
        id: m.id,
        name: m.is_system
          ? localize(`com_permission.level_${m.relation}`)
          : m.name,
        relation: m.relation as RelationLevel,
      }));
    if (options.length) {
      setModels(options);
      setSelectedModelId((current) => (
        options.some((option) => option.id === current)
          ? current
          : options.find((option) => option.relation === "viewer")?.id ?? options[0].id
      ));
      return;
    }

    setModels([]);
    setSelectedModelId("");
  }, [localize]);

  const applyGrantedPermissions = useCallback((permissions: PermissionEntry[] | undefined) => {
    const next = {
      user: new Set<number>(),
      department: new Set<number>(),
      user_group: new Set<number>(),
    };
    for (const permission of Array.isArray(permissions) ? permissions : []) {
      if (permission.subject_type in next) {
        next[permission.subject_type].add(permission.subject_id);
      }
    }
    setGrantedSubjectIds({
      user: Array.from(next.user),
      department: Array.from(next.department),
      user_group: Array.from(next.user_group),
    });
  }, []);

  useEffect(() => {
    setSelected((prev) =>
      prev.map((subject) =>
        subject.type === "department"
          ? { ...subject, include_children: includeChildren }
          : subject
      )
    );
  }, [includeChildren]);

  useEffect(() => {
    if (fixedSubjectType) {
      setSubjectType(fixedSubjectType);
      setSelected([]);
      setSelectedDepartmentSummary([]);
    }
  }, [fixedSubjectType]);

  useEffect(() => {
    let cancelled = false;
    activePermissionApi.getPermissions(resourceType, resourceId)
      .then((permissions) => {
        if (!cancelled) applyGrantedPermissions(permissions);
      })
      .catch(() => {
        if (!cancelled) setGrantedSubjectIds(EMPTY_GRANTED_SUBJECT_IDS);
      });
    return () => {
      cancelled = true;
    };
  }, [activePermissionApi, applyGrantedPermissions, resourceId, resourceType]);

  useEffect(() => {
    if (skipGrantableModelsRequest) {
      if (!prefetchedGrantableModelsLoaded) return;
      applyRelationModels(prefetchedGrantableModels, prefetchedUseDefaultModels);
      return;
    }

    activePermissionApi.getGrantableRelationModels(resourceType, resourceId)
      .then((res) => {
        applyRelationModels(res, false);
      })
      .catch(() => {
        applyRelationModels(undefined, false);
      });
  }, [
    activePermissionApi,
    applyRelationModels,
    prefetchedGrantableModels,
    prefetchedGrantableModelsLoaded,
    prefetchedUseDefaultModels,
    resourceId,
    resourceType,
    skipGrantableModelsRequest,
  ]);

  const relation = useMemo<RelationLevel>(() => {
    return models.find((m) => m.id === selectedModelId)?.relation || "viewer";
  }, [models, selectedModelId]);

  const availableModels = useMemo(() => {
    if (subjectType === "user") return models;
    return models.filter((model) => model.relation !== "owner");
  }, [models, subjectType]);

  useEffect(() => {
    if (!availableModels.length) return;
    if (availableModels.some((model) => model.id === selectedModelId)) return;
    setSelectedModelId(availableModels[0].id);
  }, [availableModels, selectedModelId]);

  const handleSubjectTypeChange = (type: SubjectType) => {
    setSubjectType(type);
    setSelected([]);
    setSelectedDepartmentSummary([]);
  };

  const handleSubmit = async () => {
    if (selected.length === 0) return;
    const grants: GrantItem[] = selected.map((s) => ({
      subject_type: s.type,
      subject_id: s.id,
      relation,
      model_id: selectedModelId,
      ...(s.type === "department"
        ? { include_children: includeChildren }
        : {}),
    }));

    setSubmitting(true);
    try {
      await activePermissionApi.authorize(resourceType, resourceId, grants, []);
      showToast({
        message: localize("com_permission.success_grant"),
        status: "success",
      });
      setSelected([]);
      setSelectedDepartmentSummary([]);
      onSuccess();
    } catch {
      showToast({
        message: localize("com_permission.error_grant_failed"),
        status: "error",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const subjectLabel = (type: SubjectType) => {
    const map: Record<SubjectType, string> = {
      user: localize("com_permission.subject_user"),
      department: localize("com_permission.subject_department"),
      user_group: localize("com_permission.subject_user_group"),
    };
    return map[type];
  };

  const showDepartmentIncludeChildrenControl =
    subjectType === "department" && !hideDepartmentIncludeChildrenControl;
  const selectedSubjectList =
    subjectType === "department" && selectedDepartmentSummary.length > 0
      ? selectedDepartmentSummary
      : selected;
  const selectedSummaryText = selectedSubjectList.map((subject) => subject.name).join("、");

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {!fixedSubjectType && (
        <div className="flex items-center gap-3">
          <div className="flex w-fit gap-1 rounded-md bg-gray-100 p-1">
            {SUBJECT_TYPES.map((type) => (
              <button
                key={type}
                className={`rounded px-3 py-1.5 text-sm transition-colors ${subjectType === type
                    ? "bg-white text-gray-900 shadow"
                    : "text-gray-500 hover:text-gray-700"
                  }`}
                onClick={() => handleSubjectTypeChange(type)}
              >
                {subjectLabel(type)}
              </button>
            ))}
          </div>

          {showDepartmentIncludeChildrenControl && (
            <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm text-[#212121]">
              <Checkbox
                checked={includeChildren}
                onCheckedChange={(value) => handleIncludeChildrenChange(value === true)}
              />
              {localize("com_permission.include_children")}
            </label>
          )}
        </div>
      )}

      <div
        className={cn(
          "min-h-0 flex-1 overflow-hidden",
          !fixedSubjectType && "mt-4"
        )}
      >
        {subjectType === "user" && (
          <SubjectSearchUser
            value={selected}
            onChange={setSelected}
            resourceType={resourceType}
            resourceId={resourceId}
            disabledIds={grantedSubjectIds.user}
            grantUsersApi={activePermissionApi.getGrantUsers}
          />
        )}
        {subjectType === "department" && (
          <SubjectSearchDepartment
            value={selected}
            onChange={setSelected}
            resourceType={resourceType}
            resourceId={resourceId}
            includeChildren={includeChildren}
            onIncludeChildrenChange={handleIncludeChildrenChange}
            onSelectionSummaryChange={setSelectedDepartmentSummary}
            disabledIds={grantedSubjectIds.department}
            grantDepartmentsApi={activePermissionApi.getGrantDepartments}
          />
        )}
        {subjectType === "user_group" && (
          <SubjectSearchUserGroup
            value={selected}
            onChange={setSelected}
            resourceType={resourceType}
            resourceId={resourceId}
            disabledIds={grantedSubjectIds.user_group}
            grantUserGroupsApi={activePermissionApi.getGrantUserGroups}
          />
        )}
      </div>

      <div className="mt-3 flex h-10 shrink-0 items-center gap-4 overflow-hidden">
        <div className="min-w-0 flex flex-1 items-center gap-2 overflow-hidden">
          <span className="shrink-0 text-[14px] font-normal leading-[22px] text-[#999999]">
            {`${localize("com_permission.selected_prefix")}${subjectLabel(subjectType)}:`}
          </span>
          <SelectedSubjectChips subjects={selectedSubjectList} fullText={selectedSummaryText} />
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span className="shrink-0 text-[14px] font-normal leading-[22px] text-[#999999]">
            {localize("com_permission.uniform_grant")}
          </span>
          <RelationSelect
            value={selectedModelId}
            onChange={setSelectedModelId}
            options={availableModels}
            className="w-[132px]"
          />
        </div>
      </div>

      <div className="mt-3 flex shrink-0 justify-end border-t pt-3">
        <Button
          onClick={handleSubmit}
          disabled={selected.length === 0 || availableModels.length === 0 || submitting}
        >
          {submitting
            ? localize("com_permission.action_submit") + "..."
            : localize("com_permission.action_submit")}
        </Button>
      </div>
    </div>
  );
}
