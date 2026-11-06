import { VisibilityType } from "~/api/knowledge";
import {
  AccessModeSelector,
  SettingsSwitchRow,
} from "~/components/permission/UnifiedPermissionControls";
import { Label } from "~/components/ui/Label";
import { useLocalize } from "~/hooks";
import { useConfirm } from "~/Providers";

interface KnowledgeSpaceAccessModeProps {
  visibility: VisibilityType;
  mode: "create" | "edit";
  isDepartmentSpace: boolean;
  disabled: boolean;
  isReleased: boolean;
  onVisibilityChange: (visibility: VisibilityType) => void;
  onReleasedChange: (isReleased: boolean) => void;
}

export function KnowledgeSpaceAccessMode({
  visibility,
  mode,
  isDepartmentSpace,
  disabled,
  isReleased,
  onVisibilityChange,
  onReleasedChange,
}: KnowledgeSpaceAccessModeProps) {
  const localize = useLocalize();
  const confirm = useConfirm();
  const isPrivate = visibility === VisibilityType.PRIVATE;

  const handleModeChange = async (value: "private" | "shared") => {
    if (disabled) return;
    if (value === "private") {
      if (isDepartmentSpace) return;
      if (mode === "edit" && !isPrivate) {
        const accepted = await confirm({
          description: localize(
            "com_subscription.confirm_knowledge_change_to_private",
          ),
          confirmText: localize("com_subscription.change_to_private"),
          cancelText: localize("com_unified_permission.cancel"),
        });
        if (!accepted) return;
      }
      onVisibilityChange(VisibilityType.PRIVATE);
      return;
    }
    if (isPrivate) onVisibilityChange(VisibilityType.APPROVAL);
  };

  return (
    <>
      <div className="space-y-2">
        <Label className="text-body font-medium text-text-1">
          <span className="mr-1 text-danger">*</span>
          {localize("com_unified_permission.access_and_share")}
        </Label>
        <AccessModeSelector
          value={isPrivate ? "private" : "shared"}
          onValueChange={(value) => void handleModeChange(value)}
          disabled={disabled}
          privateDisabled={isDepartmentSpace}
          privateLabel={localize("com_unified_permission.private")}
          privateDescription={localize(
            isDepartmentSpace
              ? "com_knowledge.department_private_disabled"
              : "com_unified_permission.private_hint",
          )}
          sharedLabel={localize("com_unified_permission.shared")}
          sharedDescription={localize("com_unified_permission.shared_hint")}
        />
      </div>
      {!isPrivate && (
        <>
          <SettingsSwitchRow
            required
            label={localize("com_unified_permission.review_join")}
            description={localize("com_unified_permission.review_join_hint")}
            checked={visibility === VisibilityType.APPROVAL}
            disabled={disabled}
            onCheckedChange={(checked) =>
              onVisibilityChange(
                checked ? VisibilityType.APPROVAL : VisibilityType.PUBLIC,
              )
            }
          />
          <SettingsSwitchRow
            required
            label={localize("com_unified_permission.publish_to_square")}
            description={localize("com_unified_permission.publish_space_hint")}
            checked={isReleased}
            disabled={disabled}
            onCheckedChange={onReleasedChange}
          />
        </>
      )}
    </>
  );
}
