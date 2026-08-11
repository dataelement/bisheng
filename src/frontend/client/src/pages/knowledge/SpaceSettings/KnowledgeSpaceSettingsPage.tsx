import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { VisibilityType } from "~/api/knowledge";
import type { SubjectType } from "~/api/permission";
import { NotificationSeverity } from "~/common";
import { PermissionDraftPanel } from "~/components/permission/PermissionDraftPanel";
import { PermissionDraftPickerDialog } from "~/components/permission/PermissionDraftPickerDialog";
import {
  AccessModeSelector,
  SettingsFooter,
  SettingsSectionHeader,
  SettingsSwitchRow,
} from "~/components/permission/UnifiedPermissionControls";
import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";
import { Input } from "~/components/ui/Input";
import { Label } from "~/components/ui/Label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/Select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/Tabs";
import { Textarea } from "~/components/ui/Textarea";
import { useAuthContext, useLocalize } from "~/hooks";
import { useConfirm, useToastContext } from "~/Providers";
import { getFullWidthLength, truncateByFullWidth } from "~/utils";
import { CreatedPermissionFailureState } from "./CreatedPermissionFailureState";
import {
  parseKnowledgeSpaceCustomTags,
  useKnowledgeSpaceSettingsForm,
} from "./useKnowledgeSpaceSettingsForm";

const MAX_NAME_LENGTH = 10;
const MAX_DESCRIPTION_LENGTH = 200;

export function KnowledgeSpaceSettingsPage() {
  const localize = useLocalize();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const { user } = useAuthContext();
  const { showToast } = useToastContext();
  const { spaceId } = useParams<{ spaceId?: string }>();
  const settings = useKnowledgeSpaceSettingsForm(spaceId);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [activeSubjectType, setActiveSubjectType] =
    useState<SubjectType>("user");
  const customTagsInputRef = useRef<HTMLInputElement | null>(null);
  const nameComposingRef = useRef(false);
  const descriptionComposingRef = useRef(false);

  useEffect(() => {
    if (!settings.submitError) return;
    showToast({
      message: settings.submitError.message,
      severity: NotificationSeverity.ERROR,
    });
  }, [settings.submitError, showToast]);

  const isPrivate = settings.form.visibility === VisibilityType.PRIVATE;
  const relationModels = useMemo(
    () =>
      settings.relationModels.map((model) => ({
        id: model.id,
        name: model.is_system
          ? localize(`com_permission.level_${model.relation}`)
          : model.name,
        relation: model.relation,
      })),
    [localize, settings.relationModels],
  );
  const creatorRow = useMemo<PermissionDraftRow | null>(() => {
    if (settings.mode !== "create" || !user) return null;
    const numericUserId = Number(user.id);
    const ownerModel = relationModels.find(
      (model) => model.relation === "owner",
    );
    return {
      subjectType: "user",
      subjectId: Number.isFinite(numericUserId) ? numericUserId : -1,
      subjectName: user.name || user.username || user.email,
      relation: "owner",
      modelId: ownerModel?.id ?? "owner",
      immutableCreator: true,
    };
  }, [relationModels, settings.mode, user]);
  const displayedPermissionRows = useMemo(
    () =>
      creatorRow
        ? [creatorRow, ...settings.permissionRows]
        : settings.permissionRows,
    [creatorRow, settings.permissionRows],
  );
  const disabledIds = useMemo<Record<SubjectType, number[]>>(
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

  const handleVisibilityModeChange = async (value: "private" | "shared") => {
    if (value === "private") {
      if (settings.mode === "edit" && !isPrivate) {
        const accepted = await confirm({
          description: localize(
            "com_subscription.confirm_knowledge_change_to_private",
          ),
          confirmText: localize("com_subscription.change_to_private"),
          cancelText: localize("com_unified_permission.cancel"),
        });
        if (!accepted) return;
      }
      settings.updateForm("visibility", VisibilityType.PRIVATE);
      return;
    }
    if (isPrivate) settings.updateForm("visibility", VisibilityType.APPROVAL);
  };

  const handleCustomTagsUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const text = typeof reader.result === "string" ? reader.result : "";
      settings.updateForm(
        "autoTagCustomText",
        parseKnowledgeSpaceCustomTags(text).join("\n"),
      );
    };
    reader.readAsText(file);
  };

  const handleSubmit = async () => {
    if (settings.autoTagFeatureVisible && settings.form.autoTagEnabled) {
      if (
        settings.form.autoTagMode === "library" &&
        !settings.form.autoTagLibraryId
      ) {
        showToast({
          message: localize("com_knowledge.auto_tag_library_required"),
          severity: NotificationSeverity.WARNING,
        });
        return;
      }
      if (settings.form.autoTagMode === "custom") {
        const customTags = parseKnowledgeSpaceCustomTags(
          settings.form.autoTagCustomText,
        );
        if (customTags.length === 0 || customTags.length > 200) {
          showToast({
            message: localize(
              customTags.length === 0
                ? "com_knowledge.auto_tag_custom_tags_required"
                : "com_knowledge.auto_tag_custom_tags_limit",
            ),
            severity: NotificationSeverity.WARNING,
          });
          return;
        }
      }
    }
    try {
      const result = await settings.submit();
      if (settings.mode === "create") {
        if (!result || result.initialPermissionResult?.status === "failed")
          return;
        showToast({
          message: localize("com_knowledge.space_create_success"),
          severity: NotificationSeverity.SUCCESS,
        });
        navigate(`/knowledge/space/${result.id}`);
        return;
      }
      showToast({
        message: localize("com_knowledge.space_updated"),
        severity: NotificationSeverity.SUCCESS,
      });
      navigate(spaceId ? `/knowledge/space/${spaceId}` : "/knowledge");
    } catch {
      // The form hook normalizes and exposes submit errors for the toast effect.
    }
  };

  if (settings.loading) {
    return (
      <div className="flex h-full items-center justify-center text-body text-text-3">
        {localize("com_ui_loading")}
      </div>
    );
  }
  if (settings.loadError) {
    return (
      <div
        role="alert"
        className="flex h-full items-center justify-center text-body text-danger"
      >
        {settings.loadError.message}
      </div>
    );
  }
  if (settings.createdSpace?.initialPermissionResult?.status === "failed") {
    return (
      <CreatedPermissionFailureState
        retryStatus={settings.permissionRetryStatus}
        onRetry={settings.retryInitialPermissions}
        onEnter={() =>
          navigate(`/knowledge/space/${settings.createdSpace?.id}`)
        }
      />
    );
  }

  const disabled = !settings.canEdit;
  const cancel = () =>
    navigate(spaceId ? `/knowledge/space/${spaceId}` : "/knowledge");
  const permissionCapabilities = {
    canChangeRelation: true,
    canRemove: true,
    relationModels,
  };

  return (
    <main
      className="flex h-full min-h-0 bg-fill-2 p-2"
      data-testid="knowledge-space-settings-page"
    >
      <div className="mx-auto flex min-h-0 w-full max-w-[1368px] flex-1 flex-col rounded-xl bg-fill-1 px-4 pt-4">
        <header className="flex h-8 shrink-0 items-center gap-3">
          <button
            type="button"
            aria-label={localize("back")}
            className="rounded p-1 text-text-2 hover:bg-fill-2"
            onClick={cancel}
          >
            <Outlined.ArrowLeft className="size-4" />
          </button>
          <span className="h-3 w-px bg-border-base" />
          <h1 className="text-body font-medium text-text-1">
            {localize(
              settings.mode === "create"
                ? "com_unified_permission.page_knowledge_create"
                : "com_unified_permission.page_knowledge_settings",
            )}
          </h1>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto py-4">
          <div className="mx-auto w-full max-w-[648px] space-y-6">
            <section className="space-y-6">
              <SettingsSectionHeader
                kind="basic"
                title={localize("com_unified_permission.basic_settings")}
              />
              <div className="space-y-4 px-6 max-[768px]:px-0">
                <div className="space-y-2">
                  <Label className="text-body font-medium text-text-1">
                    <span className="mr-1 text-danger">*</span>
                    {localize("com_subscription.knowledge_space_name")}
                  </Label>
                  <div className="relative">
                    <Input
                      value={settings.form.name}
                      disabled={disabled}
                      onCompositionStart={() => {
                        nameComposingRef.current = true;
                      }}
                      onCompositionEnd={(event) => {
                        nameComposingRef.current = false;
                        settings.updateForm(
                          "name",
                          truncateByFullWidth(
                            event.currentTarget.value,
                            MAX_NAME_LENGTH,
                          ),
                        );
                      }}
                      onChange={(event) =>
                        settings.updateForm(
                          "name",
                          nameComposingRef.current
                            ? event.target.value
                            : truncateByFullWidth(
                                event.target.value,
                                MAX_NAME_LENGTH,
                              ),
                        )
                      }
                      placeholder={localize(
                        "com_subscription.enter_knowledge_space_name",
                      )}
                      className="h-8 rounded-md pr-14"
                    />
                    <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-body-sm text-text-3">
                      {Math.ceil(getFullWidthLength(settings.form.name))}/
                      {MAX_NAME_LENGTH}
                    </span>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="text-body font-medium text-text-1">
                    {localize("com_subscription.description")}
                  </Label>
                  <Textarea
                    value={settings.form.description}
                    disabled={disabled}
                    onCompositionStart={() => {
                      descriptionComposingRef.current = true;
                    }}
                    onCompositionEnd={(event) => {
                      descriptionComposingRef.current = false;
                      settings.updateForm(
                        "description",
                        truncateByFullWidth(
                          event.currentTarget.value,
                          MAX_DESCRIPTION_LENGTH,
                        ),
                      );
                    }}
                    onChange={(event) =>
                      settings.updateForm(
                        "description",
                        descriptionComposingRef.current
                          ? event.target.value
                          : truncateByFullWidth(
                              event.target.value,
                              MAX_DESCRIPTION_LENGTH,
                            ),
                      )
                    }
                    placeholder={localize(
                      "com_subscription.enter_knowledge_space_description",
                    )}
                    className="min-h-20 resize-none rounded-md shadow-none"
                  />
                </div>
              </div>
            </section>

            {settings.autoTagFeatureVisible && settings.canEdit && (
              <section className="space-y-6">
                <SettingsSectionHeader
                  kind="advanced"
                  title={localize("com_unified_permission.advanced_settings")}
                />
                <div className="space-y-4 px-6 max-[768px]:px-0">
                  <SettingsSwitchRow
                    label={localize("com_knowledge.auto_tag_generation")}
                    checked={settings.form.autoTagEnabled}
                    onCheckedChange={(checked) =>
                      settings.updateForm("autoTagEnabled", checked)
                    }
                  />
                  {settings.form.autoTagEnabled && (
                    <Tabs
                      value={settings.form.autoTagMode}
                      onValueChange={(value) =>
                        settings.updateForm(
                          "autoTagMode",
                          value as "library" | "custom",
                        )
                      }
                    >
                      <TabsList>
                        <TabsTrigger value="library">
                          {localize("com_knowledge.auto_tag_mode_library")}
                        </TabsTrigger>
                        <TabsTrigger value="custom">
                          {localize("com_knowledge.auto_tag_mode_custom")}
                        </TabsTrigger>
                      </TabsList>
                      <TabsContent value="library" className="mt-3 space-y-2">
                        <Select
                          value={
                            settings.form.autoTagLibraryId
                              ? String(settings.form.autoTagLibraryId)
                              : undefined
                          }
                          onValueChange={(value) =>
                            settings.updateForm(
                              "autoTagLibraryId",
                              Number(value),
                            )
                          }
                        >
                          <SelectTrigger>
                            <SelectValue
                              placeholder={localize(
                                "com_knowledge.select_auto_tag_library",
                              )}
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {settings.tagLibraries.map((library) => (
                              <SelectItem
                                key={library.id}
                                value={String(library.id)}
                              >
                                {library.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        {settings.autoTagPreview.length > 0 && (
                          <div className="flex flex-wrap gap-2 text-body-sm text-text-3">
                            {settings.autoTagPreview.slice(0, 20).map((tag) => (
                              <span
                                key={tag}
                                className="rounded-full bg-fill-2 px-2 py-1"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </TabsContent>
                      <TabsContent value="custom" className="mt-3 space-y-2">
                        <div className="flex items-center justify-between text-body-sm text-text-3">
                          <span>
                            {
                              parseKnowledgeSpaceCustomTags(
                                settings.form.autoTagCustomText,
                              ).length
                            }
                            /200
                          </span>
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 text-blue-500 hover:underline"
                            onClick={() => customTagsInputRef.current?.click()}
                          >
                            <Outlined.Upload className="size-4" />
                            {localize("com_knowledge.upload_txt")}
                          </button>
                          <input
                            ref={customTagsInputRef}
                            type="file"
                            accept=".txt"
                            className="hidden"
                            onChange={handleCustomTagsUpload}
                          />
                        </div>
                        <Textarea
                          value={settings.form.autoTagCustomText}
                          onChange={(event) =>
                            settings.updateForm(
                              "autoTagCustomText",
                              event.target.value,
                            )
                          }
                          placeholder={localize(
                            "com_knowledge.auto_tag_custom_tags_placeholder",
                          )}
                          className="min-h-28 resize-none"
                        />
                      </TabsContent>
                    </Tabs>
                  )}
                </div>
              </section>
            )}

            {settings.canManagePermissions && (
              <section className="space-y-6" data-testid="permission-section">
                <SettingsSectionHeader
                  kind="permission"
                  title={localize("com_unified_permission.access_and_share")}
                />
                <div className="space-y-4 px-6 max-[768px]:px-0">
                  <div className="space-y-2">
                    <Label className="text-body font-medium text-text-1">
                      <span className="mr-1 text-danger">*</span>
                      {localize("com_unified_permission.access_and_share")}
                    </Label>
                    <AccessModeSelector
                      value={isPrivate ? "private" : "shared"}
                      onValueChange={(value) =>
                        void handleVisibilityModeChange(value)
                      }
                      disabled={!settings.canEdit}
                      privateLabel={localize("com_unified_permission.private")}
                      privateDescription={localize(
                        "com_unified_permission.private_hint",
                      )}
                      sharedLabel={localize("com_unified_permission.shared")}
                      sharedDescription={localize(
                        "com_unified_permission.shared_hint",
                      )}
                    />
                  </div>
                  {!isPrivate && (
                    <>
                      <SettingsSwitchRow
                        required
                        label={localize("com_unified_permission.review_join")}
                        description={localize(
                          "com_unified_permission.review_join_hint",
                        )}
                        checked={
                          settings.form.visibility === VisibilityType.APPROVAL
                        }
                        disabled={!settings.canEdit}
                        onCheckedChange={(checked) =>
                          settings.updateForm(
                            "visibility",
                            checked
                              ? VisibilityType.APPROVAL
                              : VisibilityType.PUBLIC,
                          )
                        }
                      />
                      <SettingsSwitchRow
                        required
                        label={localize(
                          "com_unified_permission.publish_to_square",
                        )}
                        description={localize(
                          "com_unified_permission.publish_space_hint",
                        )}
                        checked={settings.form.isReleased}
                        disabled={!settings.canEdit}
                        onCheckedChange={(checked) =>
                          settings.updateForm("isReleased", checked)
                        }
                      />
                      <PermissionDraftPanel
                        value={displayedPermissionRows}
                        onChange={(rows) =>
                          settings.replacePermissionRows(
                            rows.filter((row) => !row.immutableCreator),
                          )
                        }
                        capabilities={permissionCapabilities}
                        activeSubjectType={activeSubjectType}
                        onActiveSubjectTypeChange={setActiveSubjectType}
                        onAddAuthorization={() => setPickerOpen(true)}
                        canAddAuthorization={settings.canManagePermissions}
                      />
                    </>
                  )}
                </div>
              </section>
            )}
          </div>
        </div>

        <SettingsFooter
          centered={settings.mode === "create"}
          cancelLabel={localize("com_unified_permission.cancel")}
          submitLabel={localize(
            settings.mode === "create"
              ? "com_unified_permission.confirm_create"
              : "com_unified_permission.save",
          )}
          onCancel={cancel}
          onSubmit={() => void handleSubmit()}
          submitting={settings.submitting}
          disabled={
            !settings.form.name.trim() ||
            (!settings.canEdit && !settings.canManagePermissions)
          }
        />
      </div>

      <PermissionDraftPickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        mode={settings.mode === "create" ? "create" : "resource"}
        resourceType="knowledge_space"
        resourceId={spaceId}
        disabledIds={disabledIds}
        relationModels={relationModels}
        canAddNonUserSubjects={settings.canAddNonUserSubjects}
        onConfirm={settings.addPermissionRows}
      />
    </main>
  );
}
