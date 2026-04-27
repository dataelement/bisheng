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

/**
 * Parse a single channel filter_rules entry into a single-layer FilterGroup.
 * Multi-layer historical data is silently flattened — only the FIRST top-level rule
 * is read; deeper groups are discarded. keywords are kept as string[].
 */
function parseRuleGroupsFromFilterRule(ruleEntry: any): { groups: FilterGroup[]; topRelation: FilterRelation } {
    const topRelation: FilterRelation = ruleEntry?.relation === "or" ? "or" : "and";
    const topRules = Array.isArray(ruleEntry?.rules) ? ruleEntry.rules : [];

    if (topRules.length === 0) {
        return { groups: [], topRelation };
    }

    const firstTop = topRules[0];

    let relation: FilterRelation = topRelation;
    let conditions: FilterGroup["conditions"] = [];

    if (firstTop?.type === "multi" || Array.isArray(firstTop?.rules)) {
        // multi: take its inner singles as the single-layer conditions
        relation = firstTop?.relation === "or" ? "or" : "and";
        conditions = (firstTop.rules || [])
            .filter((x: any) => x && typeof x === "object")
            .map((leaf: any) => ({
                id: nanoid(),
                include: leaf?.rule_type !== "exclude",
                keywords: Array.isArray(leaf?.keywords) ? leaf.keywords.slice() : [],
            }));
    } else if (firstTop && typeof firstTop === "object") {
        // single rule (new shape) OR legacy flat leaf
        conditions = [{
            id: nanoid(),
            include: firstTop?.rule_type !== "exclude",
            keywords: Array.isArray(firstTop?.keywords) ? firstTop.keywords.slice() : [],
        }];
    }

    if (conditions.length === 0) {
        return { groups: [], topRelation };
    }

    return {
        groups: [{ id: nanoid(), relation, conditions }],
        topRelation: relation,
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
            // 单层视图：只读取 mainRules 中第一条的第一组，丢弃多余结构。
            const parsedMain = parseRuleGroupsFromFilterRule(mainRules[0]);
            if (parsedMain.groups.length > 0) {
                setContentFilter(true);
                setFilterGroups(parsedMain.groups);
                setTopFilterRelation(parsedMain.topRelation);
                setContentFilterCollapsed(false);
            } else {
                setContentFilter(false);
                setFilterGroups([]);
                setTopFilterRelation("and");
            }
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
                // 单层视图：每个子频道仅读取 groupList 中第一条的第一组。
                const parsedSub = parseRuleGroupsFromFilterRule(groupList[0]);
                if (parsedSub.groups.length === 0) continue;

                nextSubChannels.push({
                    id: nanoid(),
                    name,
                    collapsed: false,
                    groups: parsedSub.groups,
                    topRelation: parsedSub.topRelation,
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
                groups: [{ id: nanoid(), relation: "and", conditions: [{ id: nanoid(), include: true, keywords: [] }] }],
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
                conditions: [{ id: nanoid(), include: true, keywords: [] }]
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
