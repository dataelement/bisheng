import {
    type CreateManagerChannelPayload,
    type ManagerChannelFilterRule,
    type ManagerChannelRuleNode,
    type ManagerChannelSingleRule
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
        // Sub-channel names must be unique (case-insensitive).
        // Trim then compare by lowercase to avoid " A " vs "a" being treated as different.
        const seen = new Set<string>();
        for (const sub of data.subChannels) {
            const v = sub.name.trim();
            if (!v) continue; // handled by empty-name validation below
            const key = v.toLowerCase();
            if (seen.has(key)) {
                return localize("com_subscription.sub_channel_name_duplicate") || "子频道名称不能重复";
            }
            seen.add(key);
        }

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

    const toSingleRule = (cond: { include: boolean; keywords: string[] }): ManagerChannelSingleRule => ({
        type: "single",
        rule_type: cond.include ? "include" : "exclude",
        keywords: Array.isArray(cond.keywords)
            ? cond.keywords.map((k) => k.trim()).filter(Boolean)
            : [],
    });

    const toRuleNodes = (
        groups: Array<{ relation: "and" | "or"; conditions: Array<{ include: boolean; keywords: string[] }> }>
    ): ManagerChannelRuleNode[] => {
        return groups.map((group) => {
            const singles = group.conditions.map(toSingleRule);
            if (singles.length <= 1) return singles[0];
            return {
                type: "multi",
                relation: group.relation,
                rules: singles
            };
        }).filter(Boolean) as ManagerChannelRuleNode[];
    };

    // Main channel content filter: two-layer shape
    if (data.contentFilter && data.filterGroups.length) {
        rules.push({
            channel_type: "main",
            name: null,
            relation: data.topFilterRelation,
            rules: toRuleNodes(data.filterGroups)
        });
    }

    // Sub-channel filters: two-layer shape
    if (data.createSubChannel && data.subChannels.length) {
        for (const sub of data.subChannels) {
            if (!sub.groups || !sub.groups.length) continue;
            rules.push({
                channel_type: "sub",
                name: sub.name || "sub",
                relation: sub.topRelation,
                rules: toRuleNodes(sub.groups)
            });
        }
    }

    return rules;
}

/**
 * Build CreateManagerChannelPayload from form data.
 */
export function buildCreateChannelPayload(data: CreateChannelFormData): CreateManagerChannelPayload {
    // v2.5 Module D — travels with the channel and is persisted atomically.
    // Always include so the server can clear existing rows when the user
    // emptied the config. An undefined field would mean "leave untouched".
    // Also drop sub-entries whose sub-channel was removed from the form so
    // we don't persist orphaned config the UI no longer surfaces.
    let knowledgeSync = data.knowledgeSync;
    if (knowledgeSync) {
        const validNames = new Set(
            data.createSubChannel
                ? data.subChannels.map((s) => s.name.trim()).filter(Boolean)
                : [],
        );
        knowledgeSync = {
            ...knowledgeSync,
            subs: knowledgeSync.subs.filter((s) => validNames.has(s.sub_channel_name)),
        };
    }
    return {
        name: data.channelName.trim(),
        description: data.channelDesc.trim() || undefined,
        source_list: data.sources.map((s) => s.id),
        visibility: data.visibility,
        filter_rules: buildFilterRules(data),
        is_released: data.publishToSquare === "yes",
        knowledge_sync: knowledgeSync,
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
