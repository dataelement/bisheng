import { Button } from "@bisheng/ui";
import * as RadioGroup from "@radix-ui/react-radio-group";
import { ArrowLeft, Layers3, Plus, Settings2, ShieldCheck } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  getChannelGrantSubjectsDepartmentChildrenApi,
  getChannelGrantSubjectsUserGroupsApi,
  getChannelGrantSubjectsUsersApi,
  searchChannelGrantSubjectsDepartmentsApi,
} from "~/api/channels";
import type { RelationLevel, SelectedSubject, SubjectType } from "~/api/permission";
import { NotificationSeverity } from "~/common";
import { PermissionDraftEditor } from "~/components/permission/PermissionDraftEditor";
import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";
import { RelationSelect } from "~/components/permission/RelationSelect";
import { SubjectSearchDepartment } from "~/components/permission/SubjectSearchDepartment";
import { SubjectSearchUser } from "~/components/permission/SubjectSearchUser";
import { SubjectSearchUserGroup } from "~/components/permission/SubjectSearchUserGroup";
import { Checkbox } from "~/components/ui/Checkbox";
import { Input } from "~/components/ui/Input";
import { Label } from "~/components/ui/Label";
import { Switch } from "~/components/ui/Switch";
import { Textarea } from "~/components/ui/Textarea";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { useConfirm, useToastContext } from "~/Providers";
import { getFullWidthLength, truncateByFullWidth } from "~/utils";
import { AddSourceDropdown } from "../CreateChannel/AddSourceDropdown";
import { CrawlFeedbackDialog } from "../CreateChannel/CrawlFeedbackDialog";
import { CrawlPreviewDialog } from "../CreateChannel/CrawlPreviewDialog";
import { CrawlQueuePanel } from "../CreateChannel/CrawlQueuePanel";
import { FilterConditionEditor } from "../CreateChannel/FilterConditionEditor";
import KnowledgeSyncSection from "../CreateChannel/KnowledgeSyncSection";
import { SubChannelBlock } from "../CreateChannel/SubChannelBlock";
import { validateCreateChannelForm } from "../channelUtils";
import { extractApiStatusCode } from "../errorUtils";
import { useCrawlQueue } from "../hooks/useCrawlQueue";
import { normalizeUrlForSearch } from "../urlNormalize";
import { useChannelSettingsForm } from "./useChannelSettingsForm";

const MAX_CHANNEL_NAME = 50;
const MAX_CHANNEL_DESC = 100;
const MAX_SUB_CHANNELS = 10;
const SUBJECT_TYPES: SubjectType[] = ["user", "department", "user_group"];

interface SectionHeaderProps {
  icon: "basic" | "advanced" | "permission";
  title: string;
}

function SectionHeader({ icon, title }: SectionHeaderProps) {
  const Icon = icon === "basic" ? Layers3 : icon === "advanced" ? Settings2 : ShieldCheck;
  return (
    <div className="flex h-8 items-center gap-2 rounded-md bg-fill-2 px-3 text-body font-medium text-text-1">
      <Icon className="size-4 text-blue-500" />
      <span>{title}</span>
    </div>
  );
}

interface PermissionSubjectPickerProps {
  mode: "create" | "resource";
  channelId?: string;
  rows: PermissionDraftRow[];
  relationModels: Array<{ id: string; name: string; relation: RelationLevel }>;
  onAdd: (rows: PermissionDraftRow[]) => void;
  localize: (key: string) => string;
}

function PermissionSubjectPicker({
  mode,
  channelId,
  rows,
  relationModels,
  onAdd,
  localize,
}: PermissionSubjectPickerProps) {
  const [open, setOpen] = useState(false);
  const [subjectType, setSubjectType] = useState<SubjectType>("user");
  const [selected, setSelected] = useState<SelectedSubject[]>([]);
  const [includeChildren, setIncludeChildren] = useState(true);
  const selectableModels = useMemo(
    () => subjectType === "user"
      ? relationModels
      : relationModels.filter((model) => model.relation !== "owner"),
    [relationModels, subjectType],
  );
  const [selectedModelId, setSelectedModelId] = useState("");
  const activeModel = selectableModels.find((model) => model.id === selectedModelId)
    ?? selectableModels.find((model) => model.relation === "viewer")
    ?? selectableModels[0];
  const disabledIds = rows
    .filter((row) => row.subjectType === subjectType)
    .map((row) => row.subjectId);

  const handleSubjectTypeChange = (next: SubjectType) => {
    setSubjectType(next);
    setSelected([]);
    setSelectedModelId("");
    setIncludeChildren(true);
  };

  const handleAdd = () => {
    if (!activeModel || selected.length === 0) return;
    onAdd(selected.map((subject) => ({
      subjectType: subject.type,
      subjectId: subject.id,
      subjectName: subject.name,
      relation: activeModel.relation,
      modelId: activeModel.id,
      ...(subject.type === "department" ? { includeChildren } : {}),
    })));
    setSelected([]);
    setOpen(false);
  };

  return (
    <div className="space-y-3">
      <Button
        type="button"
        color="primary"
        variant="text"
        size="small"
        onClick={() => setOpen((value) => !value)}
      >
        <Plus className="size-4" />
        {localize("com_unified_permission.add_authorization")}
      </Button>
      {open && (
        <div className="rounded-lg border border-border-base bg-fill-1 p-3">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-md bg-fill-2 p-1">
              {SUBJECT_TYPES.map((type) => (
                <button
                  key={type}
                  type="button"
                  className={`rounded px-3 py-1 text-body-sm ${
                    subjectType === type
                      ? "bg-fill-1 text-blue-500 shadow-sm"
                      : "text-text-3"
                  }`}
                  onClick={() => handleSubjectTypeChange(type)}
                >
                  {localize(`com_permission.subject_${type}`)}
                </button>
              ))}
            </div>
            {subjectType === "department" && (
              <label className="flex items-center gap-2 text-body-sm text-text-2">
                <Checkbox
                  checked={includeChildren}
                  onCheckedChange={(value) => setIncludeChildren(value === true)}
                />
                {localize("com_permission.include_children")}
              </label>
            )}
          </div>
          <div className="h-72 min-h-0 overflow-hidden">
            {subjectType === "user" && (
              <SubjectSearchUser
                value={selected}
                onChange={setSelected}
                resourceType="channel"
                resourceId={channelId}
                mode={mode}
                disabledIds={disabledIds}
                grantUsersApi={mode === "resource"
                  ? (_resourceType, resourceId, params, config) => getChannelGrantSubjectsUsersApi(resourceId, params, config)
                  : undefined}
              />
            )}
            {subjectType === "department" && (
              <SubjectSearchDepartment
                value={selected}
                onChange={setSelected}
                resourceType="channel"
                resourceId={channelId}
                mode={mode}
                includeChildren={includeChildren}
                disabledIds={disabledIds}
                grantDepartmentChildrenApi={mode === "resource"
                  ? (_resourceType, resourceId, parentId, config) => getChannelGrantSubjectsDepartmentChildrenApi(resourceId, parentId, config)
                  : undefined}
                grantDepartmentSearchApi={mode === "resource"
                  ? (_resourceType, resourceId, keyword, limit, config) => searchChannelGrantSubjectsDepartmentsApi(resourceId, keyword, limit, config)
                  : undefined}
              />
            )}
            {subjectType === "user_group" && (
              <SubjectSearchUserGroup
                value={selected}
                onChange={setSelected}
                resourceType="channel"
                resourceId={channelId}
                mode={mode}
                disabledIds={disabledIds}
                grantUserGroupsApi={mode === "resource"
                  ? (_resourceType, resourceId, params, config) => getChannelGrantSubjectsUserGroupsApi(resourceId, params, config)
                  : undefined}
              />
            )}
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-border-base pt-3">
            <div className="flex min-w-0 items-center gap-2 text-body-sm text-text-3">
              <span>{localize("com_permission.uniform_grant")}</span>
              {activeModel && (
                <RelationSelect
                  value={activeModel.id}
                  onChange={setSelectedModelId}
                  options={selectableModels}
                  className="w-32"
                />
              )}
            </div>
            <div className="flex gap-2">
              <Button type="button" color="secondary" variant="outline" size="small" onClick={() => setOpen(false)}>
                {localize("com_unified_permission.cancel")}
              </Button>
              <Button type="button" color="primary" variant="solid" size="small" disabled={!activeModel || selected.length === 0} onClick={handleAdd}>
                {localize("com_unified_permission.add_authorization")}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function ChannelSettingsPage() {
  const { channelId } = useParams<{ channelId?: string }>();
  const settings = useChannelSettingsForm(channelId);
  const { showToast } = useToastContext();
  const confirm = useConfirm();
  const knowledgePickerHostRef = useRef<HTMLDivElement>(null);
  const [previewItemId, setPreviewItemId] = useState<string | null>(null);
  const [feedbackDialogOpen, setFeedbackDialogOpen] = useState(false);
  const form = settings.business;
  const crawlQueue = useCrawlQueue({
    onSourceAdded: (source) => {
      form.setSources((current) => current.some((item) => item.id === source.id)
        ? current
        : [...current, source]);
    },
  });
  const previewItem = previewItemId
    ? crawlQueue.queue.find((item) => item.id === previewItemId) ?? null
    : null;
  const relationOptions = settings.relationModels.map((model) => ({
    id: model.id,
    name: model.is_system
      ? settings.localize(`com_permission.level_${model.relation}`)
      : model.name,
    relation: model.relation,
  }));

  if (settings.isLoading) {
    return <div className="flex h-full items-center justify-center"><LoadingIcon /></div>;
  }

  if (settings.loadError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-body text-text-2">
        <span>{settings.localize("com_load_error")}</span>
        <Button color="secondary" variant="outline" size="small" onClick={settings.cancel}>
          {settings.localize("com_unified_permission.cancel")}
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
          <ShieldCheck className="mx-auto size-10 text-warning" />
          <h1 className="mt-4 text-h4 text-text-1">
            {settings.localize("com_unified_permission.resource_created_permission_failed")}
          </h1>
          <p className="mt-2 text-body-sm text-text-3">
            {settings.authorizationRecovery.errorCode ?? ""}
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Button color="secondary" variant="outline" size="medium" onClick={settings.enterCreatedChannel}>
              {settings.localize("com_unified_permission.enter_channel")}
            </Button>
            <Button color="primary" variant="solid" size="medium" loading={settings.submitting} onClick={handleRetryAuthorization}>
              {settings.localize("com_unified_permission.retry_permission")}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const handleVisibilityModeChange = async (mode: string) => {
    if (mode === "private") {
      if (settings.isEditMode && form.visibility !== "private") {
        const accepted = await confirm({
          description: settings.localize("com_subscription.confirm_change_to_private"),
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
        message: settings.localize("com_subscription.wait_for_crawl_completion"),
        severity: NotificationSeverity.WARNING,
      });
      return;
    }
    if (settings.canEditBusiness) {
      const validationError = validateCreateChannelForm(settings.formData, settings.localize);
      if (validationError) {
        showToast({ message: validationError, severity: NotificationSeverity.WARNING });
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

  return (
    <div ref={knowledgePickerHostRef} className="flex h-full min-h-0 flex-col bg-fill-2 p-2">
      <main className="mx-auto flex min-h-0 w-full max-w-[1368px] flex-1 flex-col overflow-hidden rounded-xl bg-fill-1">
        <header className="flex h-14 shrink-0 items-center gap-3 px-4">
          <button type="button" aria-label={settings.localize("back")} className="rounded p-1 text-text-2 hover:bg-fill-2" onClick={settings.cancel}>
            <ArrowLeft className="size-4" />
          </button>
          <span className="h-3 w-px bg-border-base" />
          <h1 className="text-body font-medium text-text-1">
            {settings.localize(settings.isEditMode
              ? "com_unified_permission.page_channel_settings"
              : "com_unified_permission.page_channel_create")}
          </h1>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-8">
          <div className={`grid items-start gap-10 max-[768px]:grid-cols-1 ${
            settings.canEditBusiness && (settings.showPermissionSection || !settings.isEditMode)
              ? "grid-cols-2"
              : "grid-cols-1"
          }`}>
            {settings.canEditBusiness && (
              <div className="space-y-10" data-testid="channel-business-column">
                <section className="space-y-6">
                  <SectionHeader icon="basic" title={settings.localize("com_unified_permission.basic_settings")} />
                  <div className="space-y-4 px-6 max-[768px]:px-0">
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <Label className="text-body text-text-1"><span className="mr-1 text-danger">*</span>{settings.localize("com_subscription.add_information_source")}</Label>
                        <CrawlQueuePanel queue={crawlQueue.queue} inProgressCount={crawlQueue.inProgressCount} panelOpen={crawlQueue.panelOpen} onPanelOpenChange={crawlQueue.setPanelOpen} onAbort={crawlQueue.abort} onOpenPreview={setPreviewItemId} onOpenFeedback={() => setFeedbackDialogOpen(true)} />
                      </div>
                      <AddSourceDropdown
                        sources={form.sources}
                        onSourcesChange={form.setSources}
                        expanded={form.showAddSourcePanel}
                        onExpandChange={form.setShowAddSourcePanel}
                        resetToken={form.sourceSearchResetToken}
                        queueInProgressCount={crawlQueue.inProgressCount}
                        onEnqueueCrawl={(url) => {
                          const normalized = normalizeUrlForSearch(url);
                          if (!normalized) return;
                          const duplicate = crawlQueue.queue.some((item) => normalizeUrlForSearch(item.url) === normalized)
                            || form.sources.some((source) => source.url && normalizeUrlForSearch(source.url) === normalized);
                          if (duplicate) {
                            showToast({ message: settings.localize("com_subscription.url_already_in_queue"), severity: NotificationSeverity.WARNING });
                            return;
                          }
                          crawlQueue.enqueue(url);
                          crawlQueue.setPanelOpen(true);
                        }}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-body text-text-1"><span className="mr-1 text-danger">*</span>{settings.localize("com_subscription.channel_name")}</Label>
                      <div className="relative">
                        <Input value={form.channelName} onChange={(event) => form.setChannelName(truncateByFullWidth(event.target.value, MAX_CHANNEL_NAME))} placeholder={settings.localize("com_subscription.enter_channel_name")} className="pr-14" />
                        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-caption text-text-4">{Math.ceil(getFullWidthLength(form.channelName))}/{MAX_CHANNEL_NAME}</span>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label className="text-body text-text-1">{settings.localize("com_subscription.channel_description")}</Label>
                      <Textarea value={form.channelDesc} onChange={(event) => form.setChannelDesc(truncateByFullWidth(event.target.value, MAX_CHANNEL_DESC))} placeholder={settings.localize("com_subscription.enter_channel_description")} className="min-h-20" />
                    </div>
                  </div>
                </section>

                <section className="space-y-6">
                  <SectionHeader icon="advanced" title={settings.localize("com_unified_permission.advanced_settings")} />
                  <div className="space-y-5 px-6 max-[768px]:px-0">
                    <div className="space-y-3">
                      <div className="flex items-center justify-between gap-4"><Label className="text-body text-text-1">{settings.localize("com_subscription.channel_content_filter")}</Label><Switch checked={form.contentFilter} onCheckedChange={form.handleContentFilterToggle} variant="tool" /></div>
                      {form.contentFilter && <FilterConditionEditor groups={form.filterGroups} topRelation={form.topFilterRelation} onGroupsChange={form.setFilterGroups} onTopRelationChange={form.setTopFilterRelation} disableFirstConditionDelete />}
                    </div>
                    <div className="space-y-3">
                      <div className="flex items-center justify-between gap-4"><Label className="text-body text-text-1">{settings.localize("com_subscription.create_sub_channel")}</Label><Switch checked={form.createSubChannel} onCheckedChange={form.handleCreateSubChannelToggle} variant="tool" /></div>
                      {form.createSubChannel && <div className="overflow-hidden rounded-lg border border-border-base">{form.subChannels.map((subChannel) => <SubChannelBlock key={subChannel.id} data={subChannel} openInEditMode={form.lastAddedSubChannelId === subChannel.id} onEditModeOpened={() => form.setLastAddedSubChannelId(null)} onNameChange={(name) => form.handleSubChannelNameChange(subChannel.id, name)} onRemove={() => form.handleRemoveSubChannel(subChannel.id)} onToggleCollapse={() => form.handleSubChannelToggleCollapse(subChannel.id)} onGroupsChange={(groups) => form.handleSubChannelGroupsChange(subChannel.id, groups)} onTopRelationChange={(relation) => form.setSubChannels((current) => current.map((item) => item.id === subChannel.id ? { ...item, topRelation: relation } : item))} />)}{form.subChannels.length < MAX_SUB_CHANNELS && <button type="button" onClick={form.handleAddSubChannel} className="flex h-12 w-full items-center gap-2 bg-fill-2 px-4 text-body text-text-2 hover:bg-fill-3"><Plus className="size-4" />{settings.localize("com_subscription.add_sub_channel")}</button>}</div>}
                    </div>
                    <KnowledgeSyncSection value={settings.knowledgeSync} onChange={settings.setKnowledgeSync} mainChannelName={form.channelName.trim()} subChannelNames={form.createSubChannel ? form.subChannels.map((item) => item.name.trim()).filter(Boolean) : []} isCreator={settings.isChannelCreator} knowledgePickerHostRef={knowledgePickerHostRef} />
                  </div>
                </section>
              </div>
            )}

            {(settings.showPermissionSection || !settings.isEditMode) && (
              <section className="space-y-6" data-testid="channel-permission-column">
                <SectionHeader icon="permission" title={settings.localize("com_unified_permission.access_and_share")} />
                <div className="space-y-5 px-6 max-[768px]:px-0">
                  <div className="space-y-3">
                    <Label className="text-body text-text-1"><span className="mr-1 text-danger">*</span>{settings.localize("com_unified_permission.access_and_share")}</Label>
                    <RadioGroup.Root disabled={!settings.canEditBusiness} value={form.visibility === "private" ? "private" : "shared"} onValueChange={handleVisibilityModeChange} className="grid grid-cols-2 gap-2 max-[480px]:grid-cols-1">
                      {["private", "shared"].map((value) => <label key={value} className="flex min-h-12 cursor-pointer items-center gap-2 rounded-lg border border-border-base px-3 text-body text-text-1 has-[[data-state=checked]]:border-blue-500 has-[[data-disabled]]:cursor-not-allowed has-[[data-disabled]]:opacity-60"><RadioGroup.Item value={value} className="flex size-4 items-center justify-center rounded-full border border-border-deep data-[state=checked]:border-blue-500 data-[state=checked]:bg-blue-500"><RadioGroup.Indicator className="size-1.5 rounded-full bg-fill-1" /></RadioGroup.Item>{settings.localize(`com_unified_permission.${value}`)}</label>)}
                    </RadioGroup.Root>
                  </div>
                  {form.visibility !== "private" && <>
                    <RadioGroup.Root disabled={!settings.canEditBusiness} value={form.visibility} onValueChange={(value) => form.setVisibility(value as "review" | "public")} className="space-y-3">
                      {[{ value: "review", key: "join_review" }, { value: "public", key: "join_public" }].map((item) => <label key={item.value} className="flex cursor-pointer items-center gap-2 text-body text-text-1"><RadioGroup.Item value={item.value} className="flex size-4 items-center justify-center rounded-full border border-border-deep data-[state=checked]:border-blue-500 data-[state=checked]:bg-blue-500"><RadioGroup.Indicator className="size-1.5 rounded-full bg-fill-1" /></RadioGroup.Item>{settings.localize(`com_unified_permission.${item.key}`)}</label>)}
                    </RadioGroup.Root>
                    <div className="flex items-center justify-between gap-4"><Label className="text-body text-text-1">{settings.localize("com_unified_permission.publish_to_square")}</Label><Switch disabled={!settings.canEditBusiness} checked={form.publishToSquare === "yes"} onCheckedChange={(checked) => form.setPublishToSquare(checked ? "yes" : "no")} variant="tool" /></div>
                    {settings.showPermissionSection && <div className="space-y-2"><Label className="text-body font-medium text-text-1">{settings.localize("com_unified_permission.permission_section")}</Label><div className="rounded-lg border border-border-base px-3"><PermissionDraftEditor value={settings.permissionDraft.rows} onChange={settings.permissionDraft.replaceRows} capabilities={{ canChangeRelation: true, canRemove: true, relationModels: relationOptions }} /></div><PermissionSubjectPicker mode={settings.isEditMode ? "resource" : "create"} channelId={channelId} rows={settings.permissionDraft.rows} relationModels={relationOptions} onAdd={settings.permissionDraft.addRows} localize={settings.localize} /></div>}
                  </>}
                </div>
              </section>
            )}
          </div>
        </div>

        <footer className="sticky bottom-0 flex shrink-0 justify-end gap-3 border-t border-border-base bg-fill-1 px-4 py-3">
          <Button color="secondary" variant="outline" size="medium" onClick={settings.cancel}>{settings.localize("com_unified_permission.cancel")}</Button>
          <Button color="primary" variant="solid" size="medium" loading={settings.submitting} disabled={crawlQueue.inProgressCount > 0} onClick={handleSubmit}>{settings.localize(settings.isEditMode ? "com_unified_permission.save" : "com_unified_permission.create")}</Button>
        </footer>
      </main>
      {previewItem?.preview && <CrawlPreviewDialog open onOpenChange={(open) => { if (!open) setPreviewItemId(null); }} url={previewItem.url} initialPreview={previewItem.preview} />}
      <CrawlFeedbackDialog open={feedbackDialogOpen} onOpenChange={setFeedbackDialogOpen} />
    </div>
  );
}
