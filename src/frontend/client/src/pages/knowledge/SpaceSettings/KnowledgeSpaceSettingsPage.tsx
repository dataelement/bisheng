import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { ArrowLeft, Plus, Upload } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { NotificationSeverity } from "~/common";
import { useConfirm, useToastContext } from "~/Providers";
import { VisibilityType } from "~/api/knowledge";
import type { SubjectType } from "~/api/permission";
import { PermissionDraftEditor } from "~/components/permission/PermissionDraftEditor";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Label } from "~/components/ui/Label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "~/components/ui/Select";
import { Switch } from "~/components/ui/Switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "~/components/ui/Tabs";
import { Textarea } from "~/components/ui/Textarea";
import { useLocalize } from "~/hooks";
import { getFullWidthLength, truncateByFullWidth } from "~/utils";
import {
  parseKnowledgeSpaceCustomTags,
  useKnowledgeSpaceSettingsForm,
} from "./useKnowledgeSpaceSettingsForm";
import { AuthorizationPicker } from "./AuthorizationPicker";
import { CreatedPermissionFailureState } from "./CreatedPermissionFailureState";

const MAX_NAME_LENGTH = 50;
const MAX_DESCRIPTION_LENGTH = 200;

export interface SectionTitleProps {
  children: ReactNode;
}

export function SectionTitle({ children }: SectionTitleProps) {
  return (
    <div className="border-b border-border-base bg-fill-1 px-5 py-2 text-body font-medium text-text-2">
      {children}
    </div>
  );
}

export function KnowledgeSpaceSettingsPage() {
  const localize = useLocalize();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const { showToast } = useToastContext();
  const { spaceId } = useParams<{ spaceId?: string }>();
  const settings = useKnowledgeSpaceSettingsForm(spaceId);
  const [pickerOpen, setPickerOpen] = useState(false);
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
  const disabledIds = useMemo<Record<SubjectType, number[]>>(
    () => ({
      user: settings.permissionRows
        .filter((row) => row.subjectType === "user")
        .map((row) => row.subjectId),
      department: settings.permissionRows
        .filter((row) => row.subjectType === "department")
        .map((row) => row.subjectId),
      user_group: settings.permissionRows
        .filter((row) => row.subjectType === "user_group")
        .map((row) => row.subjectId),
    }),
    [settings.permissionRows],
  );

  const handleVisibilityModeChange = async (value: string) => {
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
        const rawCustomTags = Array.from(
          new Set(
            settings.form.autoTagCustomText
              .split(/\r?\n/)
              .map((tag) => tag.trim())
              .filter(Boolean),
          ),
        );
        if (rawCustomTags.length === 0 || rawCustomTags.length > 200) {
          showToast({
            message: localize(
              rawCustomTags.length === 0
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
      // The hook exposes the normalized error and the toast effect reports it.
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
  const permissionCapabilities = {
    canChangeRelation: true,
    canRemove: true,
    relationModels: settings.relationModels.map((model) => ({
      id: model.id,
      name: model.name,
      relation: model.relation,
    })),
  };

  return (
    <main
      className="relative flex h-full min-h-0 flex-col bg-fill-1"
      data-testid="knowledge-space-settings-page"
    >
      <header className="flex h-14 shrink-0 items-center border-b border-border-base bg-surface-primary px-5">
        <button
          type="button"
          className="mr-3 rounded-md p-1 text-text-2 hover:bg-fill-2"
          onClick={() =>
            navigate(spaceId ? `/knowledge/space/${spaceId}` : "/knowledge")
          }
          aria-label={localize("com_unified_permission.cancel")}
        >
          <ArrowLeft className="size-5" />
        </button>
        <h1 className="text-h4 text-text-1">
          {localize(
            settings.mode === "create"
              ? "com_unified_permission.page_knowledge_create"
              : "com_unified_permission.page_knowledge_settings",
          )}
        </h1>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 pb-24">
        <div className="mx-auto w-full max-w-[648px] overflow-hidden rounded-xl border border-border-base bg-surface-primary shadow-sm">
          <SectionTitle>
            {localize("com_unified_permission.basic_settings")}
          </SectionTitle>
          <div className="space-y-5 p-5">
            <div className="space-y-2">
              <Label>
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
                  className="pr-16"
                />
                <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-body-sm text-text-3">
                  {Math.ceil(getFullWidthLength(settings.form.name))}/
                  {MAX_NAME_LENGTH}
                </span>
              </div>
            </div>
            <div className="space-y-2">
              <Label>{localize("com_subscription.description")}</Label>
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
                className="min-h-24 resize-none"
              />
            </div>
          </div>

          {settings.autoTagFeatureVisible && settings.canEdit && (
            <>
              <SectionTitle>
                {localize("com_unified_permission.advanced_settings")}
              </SectionTitle>
              <div className="space-y-4 p-5">
                <div className="flex items-center justify-between gap-4">
                  <Label>{localize("com_knowledge.auto_tag_generation")}</Label>
                  <Switch
                    variant="tool"
                    checked={settings.form.autoTagEnabled}
                    onCheckedChange={(checked) =>
                      settings.updateForm("autoTagEnabled", checked)
                    }
                  />
                </div>
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
                          settings.updateForm("autoTagLibraryId", Number(value))
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
                          className="inline-flex items-center gap-1 text-primary hover:underline"
                          onClick={() => customTagsInputRef.current?.click()}
                        >
                          <Upload className="size-4" />
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
            </>
          )}

          {settings.canManagePermissions && (
            <section data-testid="permission-section">
              <SectionTitle>
                {localize("com_unified_permission.access_and_share")}
              </SectionTitle>
              <div className="space-y-5 p-5">
                <RadioGroup.Root
                  value={isPrivate ? "private" : "shared"}
                  onValueChange={(value) =>
                    void handleVisibilityModeChange(value)
                  }
                  disabled={!settings.canEdit}
                  className="flex gap-8"
                >
                  <RadioOption
                    value="private"
                    label={localize("com_unified_permission.private")}
                  />
                  <RadioOption
                    value="shared"
                    label={localize("com_unified_permission.shared")}
                  />
                </RadioGroup.Root>
                {!isPrivate && (
                  <>
                    <RadioGroup.Root
                      value={settings.form.visibility}
                      onValueChange={(value) =>
                        settings.updateForm(
                          "visibility",
                          value as VisibilityType,
                        )
                      }
                      disabled={!settings.canEdit}
                      className="space-y-3"
                    >
                      <RadioOption
                        value={VisibilityType.APPROVAL}
                        label={localize("com_unified_permission.join_review")}
                      />
                      <RadioOption
                        value={VisibilityType.PUBLIC}
                        label={localize("com_unified_permission.join_public")}
                      />
                    </RadioGroup.Root>
                    <div className="flex items-center justify-between gap-4">
                      <Label>
                        {localize("com_unified_permission.publish_to_square")}
                      </Label>
                      <Switch
                        variant="tool"
                        checked={settings.form.isReleased}
                        disabled={!settings.canEdit}
                        onCheckedChange={(checked) =>
                          settings.updateForm("isReleased", checked)
                        }
                      />
                    </div>
                    <div
                      className="border-t border-border-base pt-4"
                      data-testid="authorization-list"
                    >
                      <div className="mb-2 flex items-center justify-between gap-4">
                        <Label>
                          {localize(
                            "com_unified_permission.permission_section",
                          )}
                        </Label>
                        <Button
                          variant="secondary"
                          className="gap-1"
                          onClick={() => setPickerOpen(true)}
                        >
                          <Plus className="size-4" />
                          {localize("com_unified_permission.add_authorization")}
                        </Button>
                      </div>
                      <PermissionDraftEditor
                        value={settings.permissionRows}
                        onChange={settings.replacePermissionRows}
                        capabilities={permissionCapabilities}
                      />
                    </div>
                  </>
                )}
              </div>
            </section>
          )}
        </div>
      </div>

      <footer className="absolute inset-x-0 bottom-0 flex justify-end gap-3 border-t border-border-base bg-surface-primary px-6 py-4">
        <Button
          variant="secondary"
          onClick={() =>
            navigate(spaceId ? `/knowledge/space/${spaceId}` : "/knowledge")
          }
        >
          {localize("com_unified_permission.cancel")}
        </Button>
        <Button
          disabled={
            settings.submitting ||
            !settings.form.name.trim() ||
            (!settings.canEdit && !settings.canManagePermissions)
          }
          onClick={() => void handleSubmit()}
        >
          {localize(
            settings.mode === "create"
              ? "com_unified_permission.create"
              : "com_unified_permission.save",
          )}
        </Button>
      </footer>

      <AuthorizationPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        mode={settings.mode}
        spaceId={spaceId}
        disabledIds={disabledIds}
        canAddNonUserSubjects={settings.canAddNonUserSubjects}
        onConfirm={settings.addSubjects}
      />
    </main>
  );
}

export interface RadioOptionProps {
  value: string;
  label: string;
}

export function RadioOption({ value, label }: RadioOptionProps) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-body text-text-1">
      <RadioGroup.Item
        value={value}
        className="flex size-4 items-center justify-center rounded-full border border-border-base data-[state=checked]:border-primary data-[state=checked]:bg-primary"
      >
        <RadioGroup.Indicator className="size-1.5 rounded-full bg-surface-primary" />
      </RadioGroup.Item>
      {label}
    </label>
  );
}
