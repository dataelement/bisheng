import { Button } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  getCreationDepartmentChildren,
  getCreationUserGroups,
  searchCreationDepartments,
  searchCreationUsers,
  type SubjectType,
} from "~/api/permission";
import { NotificationSeverity } from "~/common";
import {
  PermissionDraftPickerDialog,
  type PermissionDraftSearchApi,
} from "~/components/permission/PermissionDraftPickerDialog";
import { SettingsFooter } from "~/components/permission/UnifiedPermissionControls";
import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { useAuthContext } from "~/hooks";
import { useConfirm, useToastContext } from "~/Providers";
import { CrawlFeedbackDialog } from "../CreateChannel/CrawlFeedbackDialog";
import { CrawlPreviewDialog } from "../CreateChannel/CrawlPreviewDialog";
import { validateCreateChannelForm } from "../channelUtils";
import { extractApiStatusCode } from "../errorUtils";
import { useCrawlQueue } from "../hooks/useCrawlQueue";
import { ChannelBusinessSettings } from "./ChannelBusinessSettings";
import { ChannelPermissionSettings } from "./ChannelPermissionSettings";
import { useChannelSettingsForm } from "./useChannelSettingsForm";

export function ChannelSettingsPage() {
  const { channelId } = useParams<{ channelId?: string }>();
  const settings = useChannelSettingsForm(channelId);
  const { user } = useAuthContext();
  const { showToast } = useToastContext();
  const confirm = useConfirm();
  const knowledgePickerHostRef = useRef<HTMLDivElement>(null);
  const [previewItemId, setPreviewItemId] = useState<string | null>(null);
  const [feedbackDialogOpen, setFeedbackDialogOpen] = useState(false);
  const [permissionPickerOpen, setPermissionPickerOpen] = useState(false);
  const [activeSubjectType, setActiveSubjectType] =
    useState<SubjectType>("user");
  const form = settings.business;
  const { isEditMode, localize, relationModels } = settings;
  const crawlQueue = useCrawlQueue({
    onSourceAdded: (source) => {
      form.setSources((current) =>
        current.some((item) => item.id === source.id)
          ? current
          : [...current, source],
      );
    },
  });
  const previewItem = previewItemId
    ? (crawlQueue.queue.find((item) => item.id === previewItemId) ?? null)
    : null;
  const relationOptions = useMemo(
    () =>
      relationModels.map((model) => ({
        id: model.key,
        name: model.name,
        level: model.level,
      })),
    [relationModels],
  );
  const permissionSearchApi = useMemo<PermissionDraftSearchApi | undefined>(
    () =>
      !isEditMode
        ? {
            usersApi: (_resourceType, _resourceId, name, params, config) =>
              searchCreationUsers("channel", name, params, config),
            departmentChildrenApi: (
              _resourceType,
              _resourceId,
              parentId,
              config,
            ) =>
              getCreationDepartmentChildren("channel", parentId, config),
            departmentSearchApi: (
              _resourceType,
              _resourceId,
              keyword,
              limit,
              config,
            ) =>
              searchCreationDepartments("channel", keyword, limit, config),
            userGroupsApi: (
              _resourceType,
              _resourceId,
              config,
            ) =>
              getCreationUserGroups("channel", config),
          }
        : undefined,
    [isEditMode],
  );
  const creatorRow = useMemo<PermissionDraftRow | null>(() => {
    if (isEditMode || !user) return null;
    const numericUserId = Number(user.id);
    const ownerModel = relationOptions.find((model) => model.level === 4);
    return {
      subjectType: "user",
      subjectId: Number.isFinite(numericUserId) ? numericUserId : -1,
      subjectName: user.name || user.username || user.email,
      modelKey: ownerModel?.id ?? "owner",
      modelName: localize("creator"),
      modelLevel: ownerModel?.level ?? 4,
      protected: true,
      editable: false,
    };
  }, [isEditMode, localize, relationOptions, user]);
  const displayedPermissionRows = useMemo(
    () =>
      creatorRow
        ? [creatorRow, ...settings.permissionDraft.rows]
        : settings.permissionDraft.rows,
    [creatorRow, settings.permissionDraft.rows],
  );
  const disabledSubjectIds = useMemo<Record<SubjectType, number[]>>(
    () => ({
      user: displayedPermissionRows
        .filter((row) => row.subjectType === "user")
        .map((row) => row.subjectId),
      department: displayedPermissionRows
        .filter((row) => row.subjectType === "department")
        .map((row) => row.subjectId),
      user_group: displayedPermissionRows
        .filter((row) => row.subjectType === "user_group")
        .map((row) => row.subjectId),
    }),
    [displayedPermissionRows],
  );

  if (settings.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingIcon />
      </div>
    );
  }
  if (settings.loadError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center text-body text-text-2">
        <div className="space-y-1">
          <h1 className="text-h4 text-text-1">
            {settings.localize("com_subscription.channel_settings_load_failed")}
          </h1>
          <p className="text-body-sm text-text-3">
            {settings.localize("com_subscription.channel_settings_load_failed_desc")}
          </p>
        </div>
        <Button
          color="default"
          variant="outlined"
          size="small"
          onClick={settings.cancel}
        >
          {settings.localize("com_subscription.back_to_channel_list")}
        </Button>
      </div>
    );
  }
  if (settings.authorizationRecovery) {
    const handleRetryAuthorization = async () => {
      try {
        await settings.retryAuthorization();
      } catch (error) {
        if (!extractApiStatusCode(error)) {
          showToast({
            message: settings.localize("com_subscription.update_failed_retry"),
            severity: NotificationSeverity.ERROR,
          });
        }
      }
    };
    return (
      <div className="flex h-full items-center justify-center bg-fill-2 p-6">
        <div className="w-full max-w-lg rounded-xl border border-border-base bg-fill-1 p-8 text-center shadow-sm">
          <Outlined.PeopleSafe className="mx-auto size-10 text-warning" />
          <h1 className="mt-4 text-h4 text-text-1">
            {settings.localize(
              "com_unified_permission.resource_created_permission_failed",
            )}
          </h1>
          <p className="mt-2 text-body-sm text-text-3">
            {settings.authorizationRecovery.errorCode ?? ""}
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Button
              color="default"
              variant="outlined"
              size="medium"
              onClick={settings.enterCreatedChannel}
            >
              {settings.localize("com_unified_permission.enter_channel")}
            </Button>
            <Button
              color="primary"
              variant="solid"
              size="medium"
              loading={settings.submitting}
              onClick={handleRetryAuthorization}
            >
              {settings.localize("com_unified_permission.retry_permission")}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const handleVisibilityModeChange = async (mode: "private" | "shared") => {
    if (mode === "private") {
      if (settings.isEditMode && form.visibility !== "private") {
        const accepted = await confirm({
          description: settings.localize(
            "com_subscription.confirm_change_to_private",
          ),
          confirmText: settings.localize("com_subscription.change_to_private"),
          cancelText: settings.localize("com_unified_permission.cancel"),
        });
        if (!accepted) return;
      }
      form.setVisibility("private");
      return;
    }
    if (form.visibility === "private") form.setVisibility("review");
  };

  const handleSubmit = async () => {
    if (crawlQueue.inProgressCount > 0) {
      showToast({
        message: settings.localize(
          "com_subscription.wait_for_crawl_completion",
        ),
        severity: NotificationSeverity.WARNING,
      });
      return;
    }
    if (settings.canEditBusiness) {
      const validationError = validateCreateChannelForm(
        settings.formData,
        settings.localize,
      );
      if (validationError) {
        showToast({
          message: validationError,
          severity: NotificationSeverity.WARNING,
        });
        return;
      }
    }
    try {
      const result = await settings.submit();
      if (result?.status === "success" && settings.isEditMode) {
        showToast({
          message: settings.localize("com_subscription.save_success"),
          severity: NotificationSeverity.SUCCESS,
        });
      }
    } catch (error) {
      if (!extractApiStatusCode(error)) {
        showToast({
          message: settings.isEditMode
            ? settings.localize("com_subscription.update_failed_retry")
            : settings.localize("com_subscription.create_channel_failed_retry"),
          severity: NotificationSeverity.ERROR,
        });
      }
    }
  };

  const showPermissionColumn =
    settings.showPermissionSection || !settings.isEditMode;
  const showTwoColumns = settings.canEditBusiness && showPermissionColumn;
  const permissionCapabilities = {
    canChangeRelation: true,
    canRemove: true,
    relationModels: relationOptions,
  };

  return (
    <div
      ref={knowledgePickerHostRef}
      className="flex h-full min-h-0 bg-white"
    >
      <main className="flex min-h-0 w-full flex-1 flex-col px-4 pt-4">
        <header className="flex h-8 shrink-0 items-center gap-3">
          <button
            type="button"
            aria-label={settings.localize("back")}
            className="rounded p-1 text-text-2 hover:bg-fill-2"
            onClick={settings.cancel}
          >
            <Outlined.ArrowLeft className="size-4" />
          </button>
          <span className="h-3 w-px bg-border-base" />
          <h1 className="text-body font-medium text-text-1">
            {settings.localize(
              settings.isEditMode
                ? "com_unified_permission.page_channel_settings"
                : "com_unified_permission.page_channel_create",
            )}
          </h1>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto py-4">
          <div
            className={
              showTwoColumns
                ? "grid grid-cols-2 items-start gap-10 max-[900px]:grid-cols-1"
                : "mx-auto w-full max-w-[648px]"
            }
          >
            {settings.canEditBusiness && (
              <ChannelBusinessSettings
                settings={settings}
                crawlQueue={crawlQueue}
                knowledgePickerHostRef={knowledgePickerHostRef}
                onOpenPreview={setPreviewItemId}
                onOpenFeedback={() => setFeedbackDialogOpen(true)}
              />
            )}

            {showPermissionColumn && (
              <ChannelPermissionSettings
                settings={settings}
                displayedPermissionRows={displayedPermissionRows}
                permissionCapabilities={permissionCapabilities}
                activeSubjectType={activeSubjectType}
                onActiveSubjectTypeChange={setActiveSubjectType}
                onVisibilityModeChange={(value) =>
                  void handleVisibilityModeChange(value)
                }
                onAddAuthorization={() => setPermissionPickerOpen(true)}
              />
            )}
          </div>
        </div>

        <SettingsFooter
          centered
          cancelLabel={settings.localize("com_unified_permission.cancel")}
          submitLabel={settings.localize(
            settings.isEditMode
              ? "com_unified_permission.save"
              : "com_unified_permission.confirm_create",
          )}
          onCancel={settings.cancel}
          onSubmit={() => void handleSubmit()}
          submitting={settings.submitting}
          disabled={crawlQueue.inProgressCount > 0}
        />
      </main>

      <PermissionDraftPickerDialog
        open={permissionPickerOpen}
        onOpenChange={setPermissionPickerOpen}
        mode={settings.isEditMode ? "resource" : "create"}
        resourceType="channel"
        resourceId={channelId}
        disabledIds={disabledSubjectIds}
        relationModels={relationOptions}
        canAddNonUserSubjects={relationOptions.length > 0}
        onConfirm={settings.permissionDraft.addRows}
        searchApi={permissionSearchApi}
      />
      {previewItem?.preview && (
        <CrawlPreviewDialog
          open
          onOpenChange={(open) => {
            if (!open) setPreviewItemId(null);
          }}
          url={previewItem.url}
          initialPreview={previewItem.preview}
        />
      )}
      <CrawlFeedbackDialog
        open={feedbackDialogOpen}
        onOpenChange={setFeedbackDialogOpen}
      />
    </div>
  );
}
