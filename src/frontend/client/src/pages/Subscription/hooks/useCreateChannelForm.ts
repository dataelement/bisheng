import { useLocalize } from "~/hooks";
import { useState, useCallback, useRef } from "react";
import type { Channel, InformationSource } from "~/api/channels";
import { listManagerSourcesApi } from "~/api/channels";
import type { FilterGroup, FilterRelation } from "../CreateChannel/FilterConditionEditor";
import type { SubChannelData } from "../CreateChannel/SubChannelBlock";
import { generateUUID } from "~/utils";

const MAX_CHANNEL_NAME = 10;
const MAX_SUB_CHANNELS = 6;

type VisibilityType = "private" | "review" | "public";
type PublishToSquare = "yes" | "no";

function nanoid() {
    return generateUUID(8);
}

function parseRuleGroupsFromFilterRule(ruleEntry: any): { groups: FilterGroup[]; topRelation: FilterRelation } {
    const topRelation: FilterRelation = ruleEntry?.relation === "or" ? "or" : "and";
    const topRules = Array.isArray(ruleEntry?.rules) ? ruleEntry.rules : [];

    // New shape: relation + rules(type=single|multi)
    if (
        ruleEntry?.relation ||
        topRules.some((r: any) => r?.type === "single" || r?.type === "multi" || Array.isArray(r?.rules))
    ) {
        const groups: FilterGroup[] = topRules.flatMap((r: any) => {
            // multi rule => one group with inner relation
            if (r?.type === "multi" || Array.isArray(r?.rules)) {
                const relation: FilterRelation = r?.relation === "or" ? "or" : "and";
                const conditions = (r.rules || [])
                    .filter((x: any) => x && typeof x === "object" && (x?.type === "single" || !Array.isArray(x?.rules)))
                    .map((leaf: any) => ({
                        id: nanoid(),
                        include: leaf?.rule_type !== "exclude",
                        keywords: Array.isArray(leaf?.keywords) ? leaf.keywords.join(";") : ""
                    }));
                return conditions.length
                    ? [{ id: nanoid(), relation, conditions }]
                    : [];
            }

            // single rule => one group with one condition (inherits top relation semantically)
            if (r && typeof r === "object" && (r?.type === "single" || !Array.isArray(r?.rules))) {
                return [{
                    id: nanoid(),
                    relation: topRelation,
                    conditions: [{
                        id: nanoid(),
                        include: r?.rule_type !== "exclude",
                        keywords: Array.isArray(r?.keywords) ? r.keywords.join(";") : ""
                    }]
                }];
            }
            return [];
        });

        return { groups, topRelation };
    }

    // Old shape fallback: each entry itself is one group, relation stored on leaf items
    const relation: FilterRelation = topRules[0]?.relation === "or" ? "or" : "and";
    const conditions = topRules.map((r: any) => ({
        id: nanoid(),
        include: r?.rule_type !== "exclude",
        keywords: Array.isArray(r?.keywords) ? r.keywords.join(";") : ""
    }));
    return {
        groups: conditions.length ? [{ id: nanoid(), relation, conditions }] : [],
        topRelation: relation
    };
}

function escapeRegExp(s: string) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Highest numeric suffix among names that match the localized default pattern (e.g. 子频道名称12). */
function maxDefaultSubChannelIndex(
    subs: SubChannelData[],
    localize: (key: string, opts?: Record<string, unknown>) => string
): number {
    const marker = 900001;
    const template = localize("com_subscription.sub_channel_name_default", { index: marker });
    const markerStr = String(marker);
    if (!template.includes(markerStr)) return 0;
    const prefix = template.split(markerStr)[0] ?? "";
    const re = new RegExp(`^${escapeRegExp(prefix)}(\\d+)$`);
    let max = 0;
    for (const s of subs) {
        const m = s.name.trim().match(re);
        if (m) max = Math.max(max, parseInt(m[1], 10));
    }
    return max;
}

export function useCreateChannelForm() {
    const localize = useLocalize();
    const subChannelNameSeqRef = useRef(0);
    // Form fields
    const [sources, setSources] = useState<InformationSource[]>([]);
    const [channelName, setChannelName] = useState("");
    const [channelDesc, setChannelDesc] = useState("");
    const [visibility, setVisibility] = useState<VisibilityType>("review");
    const [publishToSquare, setPublishToSquare] = useState<PublishToSquare>("yes");
    const [contentFilter, setContentFilter] = useState(false);
    const [contentFilterCollapsed, setContentFilterCollapsed] = useState(false);
    const [filterGroups, setFilterGroups] = useState<FilterGroup[]>([]);
    const [topFilterRelation, setTopFilterRelation] = useState<FilterRelation>("and");
    const [createSubChannel, setCreateSubChannel] = useState(false);
    const [subChannels, setSubChannels] = useState<SubChannelData[]>([]);

    // UI state
    const [showAddSourcePanel, setShowAddSourcePanel] = useState(false);
    const [showCancelConfirm, setShowCancelConfirm] = useState(false);
    const [crawlDialogOpen, setCrawlDialogOpen] = useState(false);
    const [crawlUrl, setCrawlUrl] = useState("");
    const [showSuccess, setShowSuccess] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [createdChannelId, setCreatedChannelId] = useState<string | null>(null);
    const [lastAddedSubChannelId, setLastAddedSubChannelId] = useState<string | null>(null);
    const [sourceSearchResetToken, setSourceSearchResetToken] = useState(0);

    const resetForm = useCallback(() => {
        setSources([]);
        setChannelName("");
        setChannelDesc("");
        setVisibility("review");
        setPublishToSquare("yes");
        setContentFilter(false);
        setFilterGroups([]);
        setTopFilterRelation("and");
        setCreateSubChannel(false);
        setSubChannels([]);
        subChannelNameSeqRef.current = 0;
        setLastAddedSubChannelId(null);
        setShowAddSourcePanel(false);
        setShowCancelConfirm(false);
        setCrawlDialogOpen(false);
        setCrawlUrl("");
        setShowSuccess(false);
        setSubmitting(false);
        setCreatedChannelId(null);
        setSourceSearchResetToken((t) => t + 1);
    }, []);

    const initFromChannel = useCallback((channel: Channel) => {
        // 基础信息
        setChannelName(channel.name || "");
        setChannelDesc((channel as any).description || "");

        // 可见方式
        const vis = (channel as any).visibility;
        if (vis) {
            setVisibility(vis as VisibilityType);
        }

        // 是否发布到广场
        const released = (channel as any).is_released;
        if (typeof released === "boolean") {
            setPublishToSquare(released ? "yes" : "no");
        }

        const rawRules = (channel as any).filter_rules as any[] | undefined;

        // 主频道筛选条件 filter_rules（channel_type === "main"）→ filterGroups/topRelation
        const mainRules = Array.isArray(rawRules)
            ? rawRules.filter((g: any) => g.channel_type === "main")
            : [];

        if (mainRules.length > 0) {
            setContentFilter(true);
            const parsedMain = mainRules.map((g: any) => parseRuleGroupsFromFilterRule(g));
            const groups: FilterGroup[] = parsedMain.flatMap((x) => x.groups);
            setFilterGroups(groups);
            setTopFilterRelation(parsedMain[0]?.topRelation ?? "and");
            setContentFilterCollapsed(false);
        } else {
            setContentFilter(false);
            setFilterGroups([]);
            setTopFilterRelation("and");
        }

        // 子频道筛选条件 filter_rules（channel_type === "sub"）→ createSubChannel/subChannels
        const subRules = Array.isArray(rawRules)
            ? rawRules.filter((g: any) => g.channel_type === "sub")
            : [];

        if (subRules.length > 0) {
            setCreateSubChannel(true);

            // 以 name 分组，每个 name 一个子频道
            const groupedByName = new Map<string, typeof subRules>();
            for (const g of subRules) {
                const key = (g.name as string) || localize("com_subscription.sub_channel_name");
                if (!groupedByName.has(key)) {
                    groupedByName.set(key, []);
                }
                groupedByName.get(key)!.push(g);
            }

            const nextSubChannels: SubChannelData[] = [];
            for (const [name, groupList] of groupedByName.entries()) {
                const parsedSub = groupList.map((g: any) => parseRuleGroupsFromFilterRule(g));
                const groups: FilterGroup[] = parsedSub.flatMap((x) => x.groups);

                nextSubChannels.push({
                    id: nanoid(),
                    name,
                    collapsed: false,
                    groups,
                    topRelation: parsedSub[0]?.topRelation ?? "and"
                });
            }

            setSubChannels(nextSubChannels);
            subChannelNameSeqRef.current = maxDefaultSubChannelIndex(nextSubChannels, localize);
        } else {
            setCreateSubChannel(false);
            setSubChannels([]);
            subChannelNameSeqRef.current = 0;
        }
    }, [localize]);

    const loadSourcesByIds = useCallback(async (ids: string[]) => {
        if (!ids || ids.length === 0) {
            setSources([]);
            return;
        }
        try {
            const { sources: all } = await listManagerSourcesApi({
                page: 1,
                page_size: 200
            });
            const map = new Map(all.map((s) => [s.id, s]));
            const selected: InformationSource[] = ids
                .map((id) => map.get(id))
                .filter((s): s is NonNullable<typeof s> => Boolean(s))
                .map((s) => ({
                    id: s.id,
                    name: s.name,
                    avatar: s.icon,
                    url: s.original_url,
                    type: s.business_type === "wechat" ? "official_account" : "website"
                }));
            setSources(selected);
        } catch {
            // 如果拉取失败，不影响其它字段的编辑
        }
    }, []);

    // Sub-channel handlers
    const handleAddSubChannel = () => {
        if (subChannels.length >= MAX_SUB_CHANNELS) return;
        subChannelNameSeqRef.current += 1;
        const index = subChannelNameSeqRef.current;
        const id = nanoid();
        setSubChannels([
            ...subChannels,
            {
                id,
                name: localize("com_subscription.sub_channel_name_default", { index }),
                collapsed: false,
                groups: [{ id: nanoid(), relation: "and", conditions: [{ id: nanoid(), include: true, keywords: "" }] }],
                topRelation: "and"
            }
        ]);
        setLastAddedSubChannelId(id);
    };

    const handleRemoveSubChannel = (id: string) => {
        setSubChannels((prev) => {
            const next = prev.filter((s) => s.id !== id);
            if (next.length === 0) {
                setCreateSubChannel(false);
                setLastAddedSubChannelId(null);
            }
            return next;
        });
    };

    const handleSubChannelNameChange = (id: string, name: string) => {
        const trimmed = name.slice(0, MAX_CHANNEL_NAME);
        setSubChannels((prev) =>
            prev.map((s) => (s.id === id ? { ...s, name: trimmed } : s))
        );
    };

    const handleSubChannelToggleCollapse = (id: string) => {
        setSubChannels((prev) =>
            prev.map((s) => (s.id === id ? { ...s, collapsed: !s.collapsed } : s))
        );
    };

    const handleSubChannelGroupsChange = (id: string, groups: FilterGroup[]) => {
        setSubChannels((prev) => {
            // 子频道筛选条件被删空（例如点到第一个减号把组删没了）时：
            // 直接移除该子频道；若移除后没有任何子频道，则联动关闭开关
            if (!groups || groups.length === 0) {
                const next = prev.filter((s) => s.id !== id);
                if (next.length === 0) {
                    setCreateSubChannel(false);
                    setLastAddedSubChannelId(null);
                }
                return next;
            }
            return prev.map((s) => (s.id === id ? { ...s, groups } : s));
        });
    };

    // Content filter toggle with auto-init
    const handleContentFilterToggle = (v: boolean) => {
        setContentFilter(v);
        if (v && filterGroups.length === 0) {
            setFilterGroups([{
                id: nanoid(),
                relation: "and",
                conditions: [{ id: nanoid(), include: true, keywords: "" }]
            }]);
        }
    };

    // Sub-channel switch toggle with auto-init
    const handleCreateSubChannelToggle = (v: boolean) => {
        setCreateSubChannel(v);
        if (v && subChannels.length === 0) handleAddSubChannel();
    };

    return {
        // Form fields
        sources, setSources,
        channelName, setChannelName,
        channelDesc, setChannelDesc,
        visibility, setVisibility,
        publishToSquare, setPublishToSquare,
        contentFilter, contentFilterCollapsed, setContentFilterCollapsed,
        filterGroups, setFilterGroups,
        topFilterRelation, setTopFilterRelation,
        createSubChannel,
        subChannels, setSubChannels,

        // UI state
        showAddSourcePanel, setShowAddSourcePanel,
        showCancelConfirm, setShowCancelConfirm,
        crawlDialogOpen, setCrawlDialogOpen,
        crawlUrl, setCrawlUrl,
        showSuccess, setShowSuccess,
        submitting, setSubmitting,
        createdChannelId, setCreatedChannelId,
        lastAddedSubChannelId, setLastAddedSubChannelId,
        sourceSearchResetToken, setSourceSearchResetToken,

        // Handlers
        resetForm,
        initFromChannel,
        loadSourcesByIds,
        handleAddSubChannel,
        handleRemoveSubChannel,
        handleSubChannelNameChange,
        handleSubChannelToggleCollapse,
        handleSubChannelGroupsChange,
        handleContentFilterToggle,
        handleCreateSubChannelToggle,
    };
}
