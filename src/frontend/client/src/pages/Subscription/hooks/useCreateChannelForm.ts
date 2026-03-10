import { useState, useCallback } from "react";
import type { InformationSource } from "~/api/channels";
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

export function useCreateChannelForm() {
    // Form fields
    const [sources, setSources] = useState<InformationSource[]>([]);
    const [channelName, setChannelName] = useState("");
    const [channelDesc, setChannelDesc] = useState("");
    const [visibility, setVisibility] = useState<VisibilityType>("public");
    const [publishToSquare, setPublishToSquare] = useState<PublishToSquare>("no");
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

    const resetForm = useCallback(() => {
        setSources([]);
        setChannelName("");
        setChannelDesc("");
        setVisibility("public");
        setPublishToSquare("no");
        setContentFilter(false);
        setFilterGroups([]);
        setTopFilterRelation("and");
        setCreateSubChannel(false);
        setSubChannels([]);
        setLastAddedSubChannelId(null);
        setShowAddSourcePanel(false);
        setShowCancelConfirm(false);
        setCrawlDialogOpen(false);
        setCrawlUrl("");
        setShowSuccess(false);
        setSubmitting(false);
        setCreatedChannelId(null);
    }, []);

    // Sub-channel handlers
    const handleAddSubChannel = () => {
        if (subChannels.length >= MAX_SUB_CHANNELS) return;
        const id = nanoid();
        setSubChannels([
            ...subChannels,
            {
                id,
                name: "子频道名称",
                collapsed: false,
                groups: [{ id: nanoid(), relation: "and", conditions: [{ id: nanoid(), include: true, keywords: "" }] }],
                topRelation: "and"
            }
        ]);
        setLastAddedSubChannelId(id);
    };

    const handleRemoveSubChannel = (id: string) => {
        const next = subChannels.filter((s) => s.id !== id);
        setSubChannels(next);
        if (next.length === 0) setCreateSubChannel(false);
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

        // Handlers
        resetForm,
        handleAddSubChannel,
        handleRemoveSubChannel,
        handleSubChannelNameChange,
        handleSubChannelToggleCollapse,
        handleContentFilterToggle,
        handleCreateSubChannelToggle,
    };
}
