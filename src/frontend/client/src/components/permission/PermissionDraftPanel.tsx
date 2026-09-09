import { Button, Radio, RadioGroup } from "@bisheng/ui";
import { User } from "lucide-react";
import type { PendingInviteItem, SubjectType } from "~/api/permission";
import { useLocalize } from "~/hooks";
import { PermissionEmptyState } from "./PermissionEmptyState";
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
  /**
   * People who were added but still owe their own confirmation. They hold no
   * permission yet, so they are absent from `value`; without them the panel
   * shows nothing where somebody was just added and looks like the save was
   * lost.
   */
  pendingInvites?: PendingInviteItem[];
}

export function PermissionDraftPanel({
  value,
  onChange,
  capabilities,
  activeSubjectType,
  onActiveSubjectTypeChange,
  onAddAuthorization,
  canAddAuthorization = true,
  pendingInvites = [],
}: PermissionDraftPanelProps) {
  const localize = useLocalize();
  const visibleRows = value.filter((row) => row.subjectType === activeSubjectType);
  // Invitations only ever concern people, so they belong on the user tab alone.
  const visiblePendingInvites =
    activeSubjectType === "user" ? pendingInvites : [];

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
        <RadioGroup
          variant="button"
          value={activeSubjectType}
          aria-label={localize("com_unified_permission.authorization")}
          onValueChange={(value) =>
            onActiveSubjectTypeChange(value as SubjectType)
          }
        >
          {SUBJECT_TYPES.map((type) => (
            <Radio key={type} value={type}>
              {localize(`com_permission.subject_${type}`)}
            </Radio>
          ))}
        </RadioGroup>
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
        {visibleRows.length === 0 && visiblePendingInvites.length === 0 ? (
          <PermissionEmptyState
            message={localize("com_unified_permission.authorization_empty")}
          />
        ) : (
          <>
            {visibleRows.length > 0 && (
              <PermissionDraftEditor
                value={visibleRows}
                onChange={handleVisibleRowsChange}
                capabilities={capabilities}
              />
            )}
            {visiblePendingInvites.map((invite) => (
              <div
                key={invite.business_request_id}
                className="flex items-center gap-2 py-3"
                data-testid="authorization-pending-invite"
              >
                <User aria-hidden="true" className="size-4 shrink-0 text-text-3" />
                <span className="truncate text-body-sm text-text-2">
                  {invite.subject_name}
                </span>
                <span className="shrink-0 rounded-sm bg-fill-2 px-1.5 py-0.5 text-caption text-text-3">
                  {invite.execution_state === "failed"
                    ? localize("f048_permission.roster.invite_failed")
                    : localize("f048_permission.roster.invite_pending")}
                </span>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
