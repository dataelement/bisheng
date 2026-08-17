import type { SubjectType } from "~/api/permission";
import { PermissionDraftPanel } from "~/components/permission/PermissionDraftPanel";
import type { PermissionDraftEditorCapabilities } from "~/components/permission/PermissionDraftEditor";
import {
  AccessModeSelector,
  SettingsSectionHeader,
  SettingsSwitchRow,
} from "~/components/permission/UnifiedPermissionControls";
import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";
import { Label } from "~/components/ui/Label";
import type { useChannelSettingsForm } from "./useChannelSettingsForm";

interface ChannelPermissionSettingsProps {
  settings: ReturnType<typeof useChannelSettingsForm>;
  displayedPermissionRows: PermissionDraftRow[];
  permissionCapabilities: PermissionDraftEditorCapabilities;
  activeSubjectType: SubjectType;
  onActiveSubjectTypeChange: (value: SubjectType) => void;
  onVisibilityModeChange: (mode: "private" | "shared") => void;
  onAddAuthorization: () => void;
}

export function ChannelPermissionSettings({
  settings,
  displayedPermissionRows,
  permissionCapabilities,
  activeSubjectType,
  onActiveSubjectTypeChange,
  onVisibilityModeChange,
  onAddAuthorization,
}: ChannelPermissionSettingsProps) {
  const form = settings.business;

  return (
    <section className="space-y-6" data-testid="channel-permission-column">
      <SettingsSectionHeader
        kind="permission"
        title={settings.localize("com_unified_permission.access_and_share")}
      />
      <div className="space-y-4 px-6 max-[768px]:px-0">
        <div className="space-y-2">
          <Label className="text-body font-medium text-text-1">
            <span className="mr-1 text-danger">*</span>
            {settings.localize("com_unified_permission.access_and_share")}
          </Label>
          <AccessModeSelector
            value={form.visibility === "private" ? "private" : "shared"}
            onValueChange={onVisibilityModeChange}
            disabled={!settings.canEditBusiness}
            privateLabel={settings.localize("com_unified_permission.private")}
            privateDescription={settings.localize(
              "com_unified_permission.private_hint",
            )}
            sharedLabel={settings.localize("com_unified_permission.shared")}
            sharedDescription={settings.localize(
              "com_unified_permission.shared_hint",
            )}
          />
        </div>
        {form.visibility !== "private" && (
          <>
            <SettingsSwitchRow
              required
              label={settings.localize("com_unified_permission.review_join")}
              description={settings.localize(
                "com_unified_permission.review_join_hint",
              )}
              checked={form.visibility === "review"}
              disabled={!settings.canEditBusiness}
              onCheckedChange={(checked) =>
                form.setVisibility(checked ? "review" : "public")
              }
            />
            <SettingsSwitchRow
              required
              label={settings.localize(
                "com_unified_permission.publish_to_square",
              )}
              description={settings.localize(
                "com_unified_permission.publish_channel_hint",
              )}
              checked={form.publishToSquare === "yes"}
              disabled={!settings.canEditBusiness}
              onCheckedChange={(checked) =>
                form.setPublishToSquare(checked ? "yes" : "no")
              }
            />
            {settings.showPermissionSection && (
              <PermissionDraftPanel
                value={displayedPermissionRows}
                onChange={(rows) =>
                  settings.permissionDraft.replaceRows(
                    rows.filter((row) => !row.protected),
                  )
                }
                capabilities={permissionCapabilities}
                activeSubjectType={activeSubjectType}
                onActiveSubjectTypeChange={onActiveSubjectTypeChange}
                onAddAuthorization={onAddAuthorization}
              />
            )}
          </>
        )}
      </div>
    </section>
  );
}
