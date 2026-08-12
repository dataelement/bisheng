import { Outlined } from "bisheng-icons";
import type { ComponentProps } from "react";
import { NotificationSeverity } from "~/common";
import {
  SettingsSectionHeader,
  SettingsSwitchRow,
} from "~/components/permission/UnifiedPermissionControls";
import { Input } from "~/components/ui/Input";
import { Label } from "~/components/ui/Label";
import { Textarea } from "~/components/ui/Textarea";
import { useToastContext } from "~/Providers";
import { getFullWidthLength, truncateByFullWidth } from "~/utils";
import { AddSourceDropdown } from "../CreateChannel/AddSourceDropdown";
import { CrawlQueuePanel } from "../CreateChannel/CrawlQueuePanel";
import { FilterConditionEditor } from "../CreateChannel/FilterConditionEditor";
import KnowledgeSyncSection from "../CreateChannel/KnowledgeSyncSection";
import { SubChannelBlock } from "../CreateChannel/SubChannelBlock";
import type { useCrawlQueue } from "../hooks/useCrawlQueue";
import { normalizeUrlForSearch } from "../urlNormalize";
import type { useChannelSettingsForm } from "./useChannelSettingsForm";

const MAX_CHANNEL_NAME = 10;
const MAX_CHANNEL_DESC = 100;
const MAX_SUB_CHANNELS = 10;

interface ChannelBusinessSettingsProps {
  settings: ReturnType<typeof useChannelSettingsForm>;
  crawlQueue: ReturnType<typeof useCrawlQueue>;
  knowledgePickerHostRef: ComponentProps<
    typeof KnowledgeSyncSection
  >["knowledgePickerHostRef"];
  onOpenPreview: (itemId: string) => void;
  onOpenFeedback: () => void;
}

export function ChannelBusinessSettings({
  settings,
  crawlQueue,
  knowledgePickerHostRef,
  onOpenPreview,
  onOpenFeedback,
}: ChannelBusinessSettingsProps) {
  const { showToast } = useToastContext();
  const form = settings.business;

  const handleEnqueueCrawl = (url: string) => {
    const normalized = normalizeUrlForSearch(url);
    if (!normalized) return;
    const duplicate =
      crawlQueue.queue.some(
        (item) => normalizeUrlForSearch(item.url) === normalized,
      ) ||
      form.sources.some(
        (source) =>
          source.url && normalizeUrlForSearch(source.url) === normalized,
      );
    if (duplicate) {
      showToast({
        message: settings.localize("com_subscription.url_already_in_queue"),
        severity: NotificationSeverity.WARNING,
      });
      return;
    }
    crawlQueue.enqueue(url);
    crawlQueue.setPanelOpen(true);
  };

  return (
    <div className="space-y-10" data-testid="channel-business-column">
      <section className="space-y-6">
        <SettingsSectionHeader
          kind="basic"
          title={settings.localize("com_unified_permission.basic_settings")}
        />
        <div className="space-y-4 px-6 max-[768px]:px-0">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-body font-medium text-text-1">
                <span className="mr-1 text-danger">*</span>
                {settings.localize("com_subscription.add_information_source")}
              </Label>
              <CrawlQueuePanel
                queue={crawlQueue.queue}
                inProgressCount={crawlQueue.inProgressCount}
                panelOpen={crawlQueue.panelOpen}
                onPanelOpenChange={crawlQueue.setPanelOpen}
                onAbort={crawlQueue.abort}
                onOpenPreview={onOpenPreview}
                onOpenFeedback={onOpenFeedback}
              />
            </div>
            <AddSourceDropdown
              sources={form.sources}
              onSourcesChange={form.setSources}
              expanded={form.showAddSourcePanel}
              onExpandChange={form.setShowAddSourcePanel}
              resetToken={form.sourceSearchResetToken}
              queueInProgressCount={crawlQueue.inProgressCount}
              onEnqueueCrawl={handleEnqueueCrawl}
            />
          </div>
          <div className="space-y-2">
            <Label className="text-body font-medium text-text-1">
              <span className="mr-1 text-danger">*</span>
              {settings.localize("com_subscription.channel_name")}
            </Label>
            <div className="relative">
              <Input
                value={form.channelName}
                onChange={(event) =>
                  form.setChannelName(
                    truncateByFullWidth(event.target.value, MAX_CHANNEL_NAME),
                  )
                }
                placeholder={settings.localize(
                  "com_subscription.enter_channel_name",
                )}
                className="h-8 rounded-md bg-white pr-14 placeholder:text-[#999999]"
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-body-sm text-[#999999]">
                {Math.ceil(getFullWidthLength(form.channelName))}/
                {MAX_CHANNEL_NAME}
              </span>
            </div>
          </div>
          <div className="space-y-2">
            <Label className="text-body font-medium text-text-1">
              {settings.localize("com_subscription.channel_description")}
            </Label>
            <Textarea
              value={form.channelDesc}
              onChange={(event) =>
                form.setChannelDesc(
                  truncateByFullWidth(event.target.value, MAX_CHANNEL_DESC),
                )
              }
              placeholder={settings.localize(
                "com_subscription.enter_channel_description",
              )}
              className="min-h-20 resize-none rounded-md bg-white shadow-none placeholder:text-[#999999]"
            />
          </div>
        </div>
      </section>

      <section className="space-y-6">
        <SettingsSectionHeader
          kind="advanced"
          title={settings.localize("com_unified_permission.advanced_settings")}
        />
        <div className="space-y-4 px-6 max-[768px]:px-0">
          <div className="space-y-3">
            <SettingsSwitchRow
              label={settings.localize(
                "com_subscription.channel_content_filter",
              )}
              description={settings.localize(
                "com_subscription.only_filter_criteria",
              )}
              checked={form.contentFilter}
              onCheckedChange={form.handleContentFilterToggle}
            />
            {form.contentFilter && (
              <div className="bg-white" data-testid="channel-filter-conditions">
                <FilterConditionEditor
                  groups={form.filterGroups}
                  topRelation={form.topFilterRelation}
                  onGroupsChange={form.setFilterGroups}
                  onTopRelationChange={form.setTopFilterRelation}
                  disableFirstConditionDelete
                />
              </div>
            )}
          </div>
          <div className="space-y-3">
            <SettingsSwitchRow
              label={settings.localize("com_subscription.create_sub_channel")}
              description={settings.localize(
                "com_subscription.subscribe_same_filters",
              )}
              checked={form.createSubChannel}
              onCheckedChange={form.handleCreateSubChannelToggle}
            />
            {form.createSubChannel && (
              <div
                className="overflow-hidden rounded-lg border border-border-base bg-white"
                data-testid="sub-channel-list"
              >
                {form.subChannels.map((subChannel) => (
                  <SubChannelBlock
                    key={subChannel.id}
                    data={subChannel}
                    openInEditMode={
                      form.lastAddedSubChannelId === subChannel.id
                    }
                    onEditModeOpened={() => form.setLastAddedSubChannelId(null)}
                    onNameChange={(name) =>
                      form.handleSubChannelNameChange(subChannel.id, name)
                    }
                    onRemove={() => form.handleRemoveSubChannel(subChannel.id)}
                    onToggleCollapse={() =>
                      form.handleSubChannelToggleCollapse(subChannel.id)
                    }
                    onGroupsChange={(groups) =>
                      form.handleSubChannelGroupsChange(subChannel.id, groups)
                    }
                    onTopRelationChange={(relation) =>
                      form.setSubChannels((current) =>
                        current.map((item) =>
                          item.id === subChannel.id
                            ? { ...item, topRelation: relation }
                            : item,
                        ),
                      )
                    }
                  />
                ))}
                {form.subChannels.length < MAX_SUB_CHANNELS && (
                  <button
                    type="button"
                    onClick={form.handleAddSubChannel}
                    className="flex h-12 w-full items-center gap-2 bg-fill-2 px-4 text-body text-text-2 hover:bg-fill-3"
                  >
                    <Outlined.Plus className="size-4" />
                    {settings.localize("com_subscription.add_sub_channel")}
                  </button>
                )}
              </div>
            )}
          </div>
          <KnowledgeSyncSection
            value={settings.knowledgeSync}
            onChange={settings.setKnowledgeSync}
            mainChannelName={form.channelName.trim()}
            subChannelNames={
              form.createSubChannel
                ? form.subChannels
                    .map((item) => item.name.trim())
                    .filter(Boolean)
                : []
            }
            isCreator={settings.isChannelCreator}
            knowledgePickerHostRef={knowledgePickerHostRef}
          />
        </div>
      </section>
    </div>
  );
}
