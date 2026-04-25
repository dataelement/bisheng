import { Button } from "~/components/ui/Button";
import { Checkbox } from "~/components/ui/Checkbox";
import { useToastContext } from "~/Providers";
import {
  authorizeResource,
  getGrantableRelationModels,
} from "~/api/permission";
import type {
  GrantItem,
  RelationLevel,
  RelationModel,
  ResourceType,
  SelectedSubject,
  SubjectType,
} from "~/api/permission";
import { useCallback, useEffect, useMemo, useState } from "react";
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

interface PermissionGrantTabProps {
  resourceType: ResourceType;
  resourceId: string;
  onSuccess: () => void;
  prefetchedGrantableModels?: RelationModel[];
  prefetchedGrantableModelsLoaded?: boolean;
  skipGrantableModelsRequest?: boolean;
  // UI-only: when provided, hides the internal subject type switcher
  // and locks the grant form to the given subject type.
  fixedSubjectType?: SubjectType;
  includeChildren?: boolean;
  onIncludeChildrenChange?: (value: boolean) => void;
  hideDepartmentIncludeChildrenControl?: boolean;
}

export function PermissionGrantTab({
  resourceType,
  resourceId,
  onSuccess,
  prefetchedGrantableModels,
  prefetchedGrantableModelsLoaded = false,
  skipGrantableModelsRequest = false,
  fixedSubjectType,
  includeChildren: includeChildrenProp,
  onIncludeChildrenChange,
  hideDepartmentIncludeChildrenControl = false,
}: PermissionGrantTabProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const [subjectType, setSubjectType] = useState<SubjectType>(fixedSubjectType ?? "user");
  const [selected, setSelected] = useState<SelectedSubject[]>([]);
  const [models, setModels] = useState<RelationModelOption[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string>("viewer");
  const [internalIncludeChildren, setInternalIncludeChildren] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const includeChildren = includeChildrenProp ?? internalIncludeChildren;
  const handleIncludeChildrenChange = onIncludeChildrenChange ?? setInternalIncludeChildren;

  const applyRelationModels = useCallback((relationModels: RelationModel[] | undefined) => {
    const options: RelationModelOption[] = (Array.isArray(relationModels) ? relationModels : []).map((m) => ({
      id: m.id,
      name: m.is_system
        ? localize(`com_permission.level_${m.relation}`)
        : m.name,
      relation: m.relation as RelationLevel,
    }));
    if (options.length) {
      setModels(options);
      setSelectedModelId((current) => (
        options.some((option) => option.id === current) ? current : options[0].id
      ));
      return;
    }

    setModels(DEFAULT_MODELS);
    setSelectedModelId("viewer");
  }, [localize]);

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
    }
  }, [fixedSubjectType]);

  useEffect(() => {
    if (skipGrantableModelsRequest) {
      if (!prefetchedGrantableModelsLoaded) return;
      applyRelationModels(prefetchedGrantableModels);
      return;
    }

    getGrantableRelationModels(resourceType, resourceId)
      .then((res) => {
        applyRelationModels(res);
      })
      .catch(() => {
        applyRelationModels(undefined);
      });
  }, [
    applyRelationModels,
    prefetchedGrantableModels,
    prefetchedGrantableModelsLoaded,
    resourceId,
    resourceType,
    skipGrantableModelsRequest,
  ]);

  const relation = useMemo<RelationLevel>(() => {
    return models.find((m) => m.id === selectedModelId)?.relation || "viewer";
  }, [models, selectedModelId]);

  const handleSubjectTypeChange = (type: SubjectType) => {
    setSubjectType(type);
    setSelected([]);
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
      await authorizeResource(resourceType, resourceId, grants, []);
      showToast({
        message: localize("com_permission.success_grant"),
        status: "success",
      });
      setSelected([]);
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
  const selectedSummaryText = selected.map((subject) => subject.name).join("、");

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {!fixedSubjectType && (
        <div className="flex items-center gap-3">
          <div className="flex w-fit gap-1 rounded-md bg-gray-100 p-1">
            {SUBJECT_TYPES.map((type) => (
              <button
                key={type}
                className={`rounded px-3 py-1.5 text-sm transition-colors ${
                  subjectType === type
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
          <SubjectSearchUser value={selected} onChange={setSelected} />
        )}
        {subjectType === "department" && (
          <SubjectSearchDepartment
            value={selected}
            onChange={setSelected}
            includeChildren={includeChildren}
            onIncludeChildrenChange={handleIncludeChildrenChange}
          />
        )}
        {subjectType === "user_group" && (
          <SubjectSearchUserGroup value={selected} onChange={setSelected} />
        )}
      </div>

      <div className="mt-4 flex h-10 shrink-0 items-center gap-4 overflow-hidden">
        <div className="min-w-0 flex flex-1 items-center gap-2 overflow-hidden">
          <span className="shrink-0 text-[14px] font-normal leading-[22px] text-[#999999]">
            {`${localize("com_permission.selected_prefix")}${subjectLabel(subjectType)}:`}
          </span>
          <span className="truncate text-[14px] leading-[22px] text-[#4E5969]">
            {selectedSummaryText}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span className="shrink-0 text-[14px] font-normal leading-[22px] text-[#999999]">
            {localize("com_permission.uniform_grant")}
          </span>
          <RelationSelect
            value={selectedModelId}
            onChange={setSelectedModelId}
            options={models}
            className="w-[132px]"
          />
        </div>
      </div>

      <div className="mt-4 flex shrink-0 justify-end border-t pt-4">
        <Button
          onClick={handleSubmit}
          disabled={selected.length === 0 || submitting}
        >
          {submitting
            ? localize("com_permission.action_submit") + "..."
            : localize("com_permission.action_submit")}
        </Button>
      </div>
    </div>
  );
}
