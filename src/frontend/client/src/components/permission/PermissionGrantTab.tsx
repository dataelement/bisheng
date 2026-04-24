import { Button } from "~/components/ui/Button";
import { useToastContext } from "~/Providers";
import {
  authorizeResource,
  getGrantableRelationModels,
} from "~/api/permission";
import type {
  GrantItem,
  RelationLevel,
  ResourceType,
  SelectedSubject,
  SubjectType,
} from "~/api/permission";
import { X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocalize } from "~/hooks";
import { RelationModelOption, RelationSelect } from "./RelationSelect";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";
import { SubjectSearchUser } from "./SubjectSearchUser";
import { SubjectSearchUserGroup } from "./SubjectSearchUserGroup";

const SUBJECT_TYPES: SubjectType[] = ["user", "department", "user_group"];

interface PermissionGrantTabProps {
  resourceType: ResourceType;
  resourceId: string;
  onSuccess: () => void;
}

export function PermissionGrantTab({
  resourceType,
  resourceId,
  onSuccess,
}: PermissionGrantTabProps) {
  const localize = useLocalize();
  const { showToast } = useToastContext();
  const [subjectType, setSubjectType] = useState<SubjectType>("user");
  const [selected, setSelected] = useState<SelectedSubject[]>([]);
  const [models, setModels] = useState<RelationModelOption[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string>("viewer");
  const [includeChildren, setIncludeChildren] = useState(true);
  const [submitting, setSubmitting] = useState(false);

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
    getGrantableRelationModels(resourceType, resourceId)
      .then((res) => {
        const options: RelationModelOption[] = (Array.isArray(res) ? res : []).map((m) => ({
          id: m.id,
          name: m.is_system
            ? localize(`com_permission.level_${m.relation}`)
            : m.name,
          relation: m.relation as RelationLevel,
        }));
        if (options.length) {
          setModels(options);
          setSelectedModelId(options[0].id);
        }
      })
      .catch(() => {
        // fallback handled by RelationSelect
      });
  }, [resourceType, resourceId]);

  const relation = useMemo<RelationLevel>(() => {
    return models.find((m) => m.id === selectedModelId)?.relation || "viewer";
  }, [models, selectedModelId]);

  const handleSubjectTypeChange = (type: SubjectType) => {
    setSubjectType(type);
    setSelected([]);
  };

  const removeSelected = (id: number) => {
    setSelected(selected.filter((s) => s.id !== id));
  };

  const handleSubmit = async () => {
    if (selected.length === 0) return;
    const grants: GrantItem[] = selected.map((s) => ({
      subject_type: s.type,
      subject_id: s.id,
      relation,
      model_id: selectedModelId,
      ...(s.type === "department"
        ? { include_children: Boolean(s.include_children) }
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

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-1 rounded-md bg-gray-100 p-1 w-fit">
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

      {subjectType === "user" && (
        <SubjectSearchUser value={selected} onChange={setSelected} />
      )}
      {subjectType === "department" && (
        <SubjectSearchDepartment
          value={selected}
          onChange={setSelected}
          includeChildren={includeChildren}
          onIncludeChildrenChange={setIncludeChildren}
        />
      )}
      {subjectType === "user_group" && (
        <SubjectSearchUserGroup value={selected} onChange={setSelected} />
      )}

      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selected.map((s) => (
            <span
              key={`${s.type}-${s.id}`}
              className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-0.5 text-xs"
            >
              {s.name}
              <button
                className="hover:text-red-500"
                onClick={() => removeSelected(s.id)}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 border-t pt-2">
        <RelationSelect
          value={selectedModelId}
          onChange={setSelectedModelId}
          options={models}
          className="w-[160px]"
        />
        <Button
          onClick={handleSubmit}
          disabled={selected.length === 0 || submitting}
          className="ml-auto"
        >
          {submitting
            ? localize("com_permission.action_submit") + "..."
            : localize("com_permission.action_submit")}
        </Button>
      </div>
    </div>
  );
}
