import {
    type CreateManagerChannelPayload,
    type ManagerChannelFilterRule,
    type ManagerChannelRuleItem
} from "~/api/channels";
import { type KnowledgeSpace, SpaceRole, VisibilityType } from "~/api/knowledge";
import type { CreateChannelFormData } from "./CreateChannel/CreateChannelDrawer";
import type { Channel } from "~/api/channels";
import { validateFilterGroups } from "./CreateChannel/FilterConditionEditor";

/**
 * Validate the entire form data before submission.
 * Returns an error message string if invalid, or null if valid.
 * The caller is responsible for displaying the message via toast.
 */
export function validateCreateChannelForm(
    data: CreateChannelFormData,
    localize: (key: string) => string
): string | null {
    if (data.sources.length < 1) {
        return localize("com_subscription.need_one_source") || localize("com_subscription.at_least_one_source");
    }
    if (!data.channelName.trim()) {
        return localize("com_subscription.cannot_empty_channel_name");
    }
    if (data.contentFilter) {
        const err = validateFilterGroups(data.filterGroups, localize);
        if (err) return err;
    }
    if (data.createSubChannel) {
        for (const sub of data.subChannels) {
            if (!sub.name.trim()) {
                return localize("com_subscription.cannot_subchannel_name");
            }
            const err = validateFilterGroups(sub.groups, localize);
            if (err) return localize("com_subscription.cannot_filter_criteria");
        }
    }
    return null;
}


/**
 * Build filter_rules payload from form data for channel creation API.
 */
export function buildFilterRules(data: CreateChannelFormData): ManagerChannelFilterRule[] {
    const rules: ManagerChannelFilterRule[] = [];

    // Main channel content filter
    if (data.contentFilter && data.filterGroups.length) {
        for (const group of data.filterGroups) {
            const groupRules: ManagerChannelRuleItem[] = group.conditions.map((cond) => {
                const keywords =
                    cond.keywords
                        ?.split(/[;；]/)
                        .map((k: string) => k.trim())
                        .filter(Boolean) || [];
                return {
                    rule_type: cond.include ? "include" : "exclude",
                    keywords,
                    // Persist top-level relation selected in UI.
                    relation: data.topFilterRelation
                };
            });
            rules.push({
                rules: groupRules,
                channel_type: "main",
                name: "main"
            });
        }
    }

    // Sub-channel filters
    if (data.createSubChannel && data.subChannels.length) {
        for (const sub of data.subChannels) {
            if (!sub.groups || !sub.groups.length) continue;
            for (const group of sub.groups) {
                const groupRules: ManagerChannelRuleItem[] = group.conditions.map((cond) => {
                    const keywords =
                        cond.keywords
                            ?.split(/[;；]/)
                            .map((k: string) => k.trim())
                            .filter(Boolean) || [];
                    return {
                        rule_type: cond.include ? "include" : "exclude",
                        keywords,
                        // Persist each sub-channel's top-level relation.
                        relation: sub.topRelation
                    };
                });
                rules.push({
                    rules: groupRules,
                    channel_type: "sub",
                    name: sub.name || "sub"
                });
            }
        }
    }

    return rules;
}

/**
 * Build CreateManagerChannelPayload from form data.
 */
export function buildCreateChannelPayload(data: CreateChannelFormData): CreateManagerChannelPayload {
    return {
        name: data.channelName.trim(),
        description: data.channelDesc.trim() || undefined,
        source_list: data.sources.map((s) => s.id),
        visibility: data.visibility,
        filter_rules: buildFilterRules(data),
        is_released: data.publishToSquare === "yes"
    };
}

/**
 * Convert a Channel to a KnowledgeSpace for the member dialog.
 */
export function toMemberDialogSpace(channel?: Channel | null): KnowledgeSpace {
    if (channel) {
        return {
            id: channel.id,
            name: channel.name,
            description: channel.description || "",
            visibility: VisibilityType.PUBLIC,
            creator: channel.creator,
            creatorId: channel.creatorId,
            memberCount: channel.subscriberCount || 0,
            fileCount: 0,
            totalFileCount: 0,
            role: channel.role as unknown as SpaceRole,
            isPinned: channel.isPinned,
            createdAt: channel.createdAt,
            updatedAt: channel.updatedAt,
            tags: []
        };
    }
    return {
        id: "temp-channel-space",
        name: "频道成员",
        description: "",
        visibility: VisibilityType.PUBLIC,
        creator: "创建者",
        creatorId: "creator",
        memberCount: 0,
        fileCount: 0,
        totalFileCount: 0,
        role: SpaceRole.CREATOR,
        isPinned: false,
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        tags: []
    };
}
