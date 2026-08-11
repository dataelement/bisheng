import { Button } from "@bisheng/ui";
import type { SubjectType } from "~/api/permission";
import { useLocalize } from "~/hooks";
import { PermissionDraftEditor, type PermissionDraftEditorCapabilities } from "./PermissionDraftEditor";
import { getPermissionDraftRowKey, type PermissionDraftRow } from "./usePermissionDraft";

const SUBJECT_TYPES: SubjectType[] = ["user", "department", "user_group"];

interface PermissionDraftPanelProps {
  value: PermissionDraftRow[];
  onChange: (rows: PermissionDraftRow[]) => void;
  capabilities: PermissionDraftEditorCapabilities;
  activeSubjectType: SubjectType;
  onActiveSubjectTypeChange: (type: SubjectType) => void;
  onAddAuthorization: () => void;
  canAddAuthorization?: boolean;
}

export function PermissionDraftPanel({
  value,
  onChange,
  capabilities,
  activeSubjectType,
  onActiveSubjectTypeChange,
  onAddAuthorization,
  canAddAuthorization = true,
}: PermissionDraftPanelProps) {
  const localize = useLocalize();
  const visibleRows = value.filter((row) => row.subjectType === activeSubjectType);

  const handleVisibleRowsChange = (nextVisibleRows: PermissionDraftRow[]) => {
    const visibleKeys = new Set(visibleRows.map(getPermissionDraftRowKey));
    onChange([
      ...value.filter((row) => !visibleKeys.has(getPermissionDraftRowKey(row))),
      ...nextVisibleRows,
    ]);
  };

  return (
    <div className="space-y-2" data-testid="authorization-list">
      <div className="text-body font-medium text-text-1">
        {localize("com_unified_permission.authorization")}
      </div>
      <div className="flex items-center justify-between gap-3">
        <div className="inline-flex rounded-md bg-fill-2 p-[3px]">
          {SUBJECT_TYPES.map((type) => (
            <button
              key={type}
              type="button"
              className={`rounded px-3 py-0.5 text-body ${
                activeSubjectType === type
                  ? "bg-blue-500/[0.15] font-medium text-blue-500"
                  : "text-text-3"
              }`}
              onClick={() => onActiveSubjectTypeChange(type)}
            >
              {localize(`com_permission.subject_${type}`)}
            </button>
          ))}
        </div>
        {canAddAuthorization && (
          <Button
            type="button"
            color="primary"
            variant="filled"
            size="small"
            onClick={onAddAuthorization}
          >
            {localize("com_unified_permission.add_authorization")}
          </Button>
        )}
      </div>
      <div className="max-h-[480px] min-h-11 overflow-y-auto rounded-xl border border-border-base px-3">
        <PermissionDraftEditor
          value={visibleRows}
          onChange={handleVisibleRowsChange}
          capabilities={capabilities}
        />
      </div>
    </div>
  );
}
