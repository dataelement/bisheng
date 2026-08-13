import { Button } from "@bisheng/ui";
import type { SubjectType } from "~/api/permission";
import { useLocalize } from "~/hooks";
import { PermissionEmptyState } from "./PermissionEmptyState";
import { PermissionDraftEditor, type PermissionDraftEditorCapabilities } from "./PermissionDraftEditor";
import {
  SUBJECT_TAB_BUTTON_ACTIVE_CLASS,
  SUBJECT_TAB_BUTTON_CLASS,
  SUBJECT_TAB_BUTTON_INACTIVE_CLASS,
  SUBJECT_TAB_LIST_CLASS,
} from "./permissionDialogStyles";
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
        <div className={`inline-flex items-center justify-center ${SUBJECT_TAB_LIST_CLASS}`}>
          {SUBJECT_TYPES.map((type) => (
            <button
              key={type}
              type="button"
              className={`${SUBJECT_TAB_BUTTON_CLASS} ${
                activeSubjectType === type
                  ? SUBJECT_TAB_BUTTON_ACTIVE_CLASS
                  : SUBJECT_TAB_BUTTON_INACTIVE_CLASS
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
            className="h-7 px-3"
            onClick={onAddAuthorization}
          >
            {localize("com_unified_permission.add_authorization")}
          </Button>
        )}
      </div>
      <div
        className="h-[400px] overflow-y-auto rounded-xl bg-white pl-2"
        data-testid="authorization-list-body"
      >
        {visibleRows.length === 0 ? (
          <PermissionEmptyState
            message={localize("com_unified_permission.authorization_empty")}
          />
        ) : (
          <PermissionDraftEditor
            value={visibleRows}
            onChange={handleVisibleRowsChange}
            capabilities={capabilities}
          />
        )}
      </div>
    </div>
  );
}
