/**
 * KnowledgeSyncSection — v2.5 Module D configuration UI.
 *
 * Pure controlled component. Owned by the parent CreateChannelDrawer, which
 * hoists the draft in `value` and passes `onChange`. No API calls happen here
 * — the draft is persisted atomically when the creator clicks Save on the
 * drawer (backend accepts a `knowledge_sync` field on Channel create/update).
 *
 * Requirement coverage (v2.5 Module D):
 *   • Creator-only visibility (controlled by `isCreator` prop)
 *   • "同步至知识空间" toggle (default off)
 *   • Bound spaces rendered as `grey parent / bold leaf` rows
 *   • "添加知识空间" always visible below the list; reuses AddToKnowledgeModal
 *   • "为每个子频道单独设置" toggle with per-sub-channel expansion
 *   • Sub-channel name updates in parent form auto-propagate to this section
 */
import { ChevronDown, ChevronUp, PlusSquare } from "lucide-react";
import { useMemo, useState, type RefObject } from "react";
import { Switch } from "~/components/ui";
import type {
    KnowledgeSyncConfig,
    KnowledgeSyncSpaceItem,
    KnowledgeSyncSubConfig,
} from "~/api/channels";
import {
    AddToKnowledgeModal,
    type AddToKnowledgeSelection,
} from "~/pages/Subscription/Article/AddToKnowledgeModal";
import { useLocalize } from "~/hooks";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import SyncSpaceItem from "./SyncSpaceItem";

export type KnowledgeSyncDraft = KnowledgeSyncConfig;

export interface KnowledgeSyncSectionProps {
    /** Current draft value. Must always be supplied by the parent. */
    value: KnowledgeSyncDraft;
    /** Called with the next draft. Standard controlled-component contract. */
    onChange: (next: KnowledgeSyncDraft) => void;
    /** Name of the main channel */
    mainChannelName?: string;
    /** Sub-channel names from the parent form. Drives the per-sub-channel list. */
    subChannelNames: string[];
    /** Only creators get to see this whole section. */
    isCreator: boolean;
    /** 创建/编辑频道抽屉内的挂载点：H5 下选择知识空间在此容器内下钻，而非再叠一层 Dialog */
    knowledgePickerHostRef?: RefObject<HTMLDivElement | null>;
}

type AddTarget =
    | { type: "main" }
    | { type: "sub"; subChannelName: string };

const emptyDraft = (): KnowledgeSyncDraft => ({
    main: { enabled: false, spaces: [] },
    subs: [],
});

/** Normalise a draft to guarantee default-shaped sub-entries for every name in
 * `subChannelNames`. Entries whose sub-channel was removed from the form are
 * dropped entirely from the UI — the backend will see them disappear on save. */
function withSubChannelNames(
    draft: KnowledgeSyncDraft,
    names: string[],
): { rows: KnowledgeSyncSubConfig[]; known: Set<string> } {
    const known = new Set(names);
    const byName = new Map(draft.subs.map((s) => [s.sub_channel_name, s]));
    const rows: KnowledgeSyncSubConfig[] = [];
    // Saved sub-channels (still in the form) first, in draft order — spec 3.3.2.4.
    for (const s of draft.subs) {
        if (known.has(s.sub_channel_name)) rows.push({ ...s });
    }
    // Then newly-added names (no draft yet).
    for (const name of names) {
        if (!byName.has(name)) {
            rows.push({ sub_channel_name: name, enabled: false, spaces: [] });
        }
    }
    return { rows, known };
}

export default function KnowledgeSyncSection({
    value,
    onChange,
    mainChannelName,
    subChannelNames,
    isCreator,
    knowledgePickerHostRef,
}: KnowledgeSyncSectionProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const draft = value || emptyDraft();

    const [modalOpen, setModalOpen] = useState(false);
    const [addTarget, setAddTarget] = useState<AddTarget | null>(null);
    // Sub-channel names that are expanded. Per spec 3.3.2.5/6, the first
    // sub-channel and any sub-channel with bound spaces default to expanded.
    const [expandedSubs, setExpandedSubs] = useState<Set<string> | null>(null);
    // UI-only override for the "per-sub-channel" switch. Not persisted: the
    // backend only sees individual sub entries. We derive an initial value
    // from the draft so existing configs show the switch on automatically.
    // Once the user explicitly toggles it, their choice wins.
    const [subModeOverride, setSubModeOverride] = useState<boolean | null>(null);

    const { rows: subRows } = useMemo(
        () => withSubChannelNames(draft, subChannelNames),
        [draft, subChannelNames],
    );

    // Derive the default-expanded set lazily on first render so draft updates
    // after that point do not collapse the user's choices.
    const effectiveExpanded = useMemo(() => {
        if (expandedSubs) return expandedSubs;
        const s = new Set<string>();
        if (subRows.length > 0) s.add(subRows[0].sub_channel_name);
        for (const r of subRows) {
            if (r.spaces.length > 0) s.add(r.sub_channel_name);
        }
        return s;
    }, [expandedSubs, subRows]);

    if (!isCreator) return null;

    // --- handlers ---------------------------------------------------------

    const setMainEnabled = (next: boolean) => {
        onChange({ ...draft, main: { ...draft.main, enabled: next } });
    };

    const subModeDerived = draft.subs.some(
        (s) => s.enabled || s.spaces.length > 0,
    );
    const subModeActive = subModeOverride ?? subModeDerived;

    const setSubMode = (next: boolean) => {
        setSubModeOverride(next);
        // Toggling off disables every sub row but keeps the selected spaces
        // around so they come back if the user flips it on again.
        if (!next) {
            onChange({
                ...draft,
                subs: draft.subs.map((s) => ({ ...s, enabled: false })),
            });
        }
    };



    const deleteMainSpace = (spaceKey: string) => {
        onChange({
            ...draft,
            main: {
                ...draft.main,
                spaces: draft.main.spaces.filter((s) => spaceKeyOf(s) !== spaceKey),
            },
        });
    };

    const deleteSubSpace = (name: string, spaceKey: string) => {
        onChange({
            ...draft,
            subs: draft.subs.map((s) =>
                s.sub_channel_name === name
                    ? { ...s, spaces: s.spaces.filter((x) => spaceKeyOf(x) !== spaceKey) }
                    : s,
            ),
        });
    };

    const handleAdd = (target: AddTarget) => {
        setAddTarget(target);
        setModalOpen(true);
    };

    const handleSyncSelect = (sel: AddToKnowledgeSelection) => {
        if (!addTarget) return;
        const newSpace: KnowledgeSyncSpaceItem = {
            knowledge_space_id: sel.knowledgeSpaceId,
            knowledge_space_name: sel.knowledgeSpaceName,
            folder_id: sel.folderId,
            folder_path: sel.folderPath,
        };
        const newKey = spaceKeyOf(newSpace);
        // TC-038: block repeat adds of the same (space_id, folder_id) pair
        // to the same scope. We scope the check per-target so the same
        // binding can still appear on main vs. sub, or on two subs.
        const notifyDuplicate = () => {
            showToast?.({
                message:
                    localize?.("com_subscription.knowledge_space_already_added"),
                severity: NotificationSeverity.WARNING,
            });
            setAddTarget(null);
        };
        if (addTarget.type === "main") {
            if (draft.main.spaces.some((s) => spaceKeyOf(s) === newKey)) {
                notifyDuplicate();
                return;
            }
            onChange({
                ...draft,
                main: {
                    enabled: true,
                    spaces: [...draft.main.spaces, newSpace],
                },
            });
        } else {
            const name = addTarget.subChannelName;
            const existingSub = draft.subs.find((s) => s.sub_channel_name === name);
            if (existingSub?.spaces.some((s) => spaceKeyOf(s) === newKey)) {
                notifyDuplicate();
                return;
            }
            onChange({
                ...draft,
                subs: existingSub
                    ? draft.subs.map((s) =>
                        s.sub_channel_name === name
                            ? { ...s, enabled: true, spaces: [...s.spaces, newSpace] }
                            : s,
                    )
                    : [
                        ...draft.subs,
                        { sub_channel_name: name, enabled: true, spaces: [newSpace] },
                    ],
            });
            // Auto-expand the sub-channel we just added a space to.
            setExpandedSubs((prev) => {
                const next = new Set(prev ?? effectiveExpanded);
                next.add(name);
                return next;
            });
        }
        setAddTarget(null);
    };

    const toggleExpand = (name: string) => {
        setExpandedSubs((prev) => {
            const base = new Set(prev ?? effectiveExpanded);
            if (base.has(name)) base.delete(name);
            else base.add(name);
            return base;
        });
    };

    // --- render -----------------------------------------------------------

    const noSubChannels = subChannelNames.length === 0;
    const mainEnabled = draft.main.enabled;

    return (
        <div className="mt-6">
            <div className="flex items-start justify-between gap-4">
                <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                    <span className="text-[14px] font-medium text-[#1D2129]">
                        {localize?.("com_subscription.sync_to_knowledge_space") ||
                            "同步至知识空间"}
                    </span>
                    <span className="text-[12px] text-[#86909C]">
                        {localize?.("com_subscription.sync_to_knowledge_space_hint") ||
                            "该频道下的内容会自动同步到知识空间"}
                    </span>
                </div>
                <Switch
                    checked={mainEnabled}
                    onCheckedChange={setMainEnabled}
                    className="shrink-0 data-[state=checked]:bg-[#165DFF] data-[state=unchecked]:bg-[#E5E6EB]"
                />
            </div>

            {mainEnabled && (
                <div className="mt-3 rounded-md border border-[#E5E6EB] text-[#1D2129] bg-[#fbfbfb]">
                    <div className="px-4 py-3 text-[14px] font-medium">
                        {mainChannelName || localize?.("com_subscription.main_channel") || "频道名称"}
                    </div>
                    <div className="space-y-1 px-2 pb-2">
                        {draft.main.spaces.map((s) => (
                            <SyncSpaceItem
                                key={spaceKeyOf(s)}
                                space={s}
                                onDelete={() => deleteMainSpace(spaceKeyOf(s))}
                            />
                        ))}
                        <button
                            type="button"
                            onClick={() => handleAdd({ type: "main" })}
                            className="flex w-full items-center gap-1.5 rounded-md px-2 py-2 text-[13px] text-[#4E5969] hover:bg-[#F7F8FA]"
                        >
                            <PlusSquare className="size-3.5 shrink-0 text-gray-700" />
                            <span>
                                {localize?.("com_subscription.add_knowledge_space")}
                            </span>
                        </button>
                    </div>
                </div>
            )}

            {mainEnabled && (
                <div className="mt-6">
                    <div className="flex items-start justify-between gap-4">
                        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                            <span
                                className={
                                    "text-[14px] font-medium " +
                                    (noSubChannels ? "text-[#C9CDD4]" : "text-[#1D2129]")
                                }
                            >
                                {localize?.("com_subscription.per_sub_channel_sync") ||
                                    "为每个子频道单独设置"}
                            </span>
                            <span
                                className={
                                    "text-[14px] " +
                                    (noSubChannels ? "text-[#C9CDD4]" : "text-[#86909C]")
                                }
                            >
                                {localize?.("com_subscription.per_sub_channel_sync_hint") ||
                                    "该子频道下的内容会自动同步到知识空间"}
                            </span>
                        </div>
                        <Switch
                            checked={!noSubChannels && subModeActive}
                            disabled={noSubChannels}
                            onCheckedChange={setSubMode}
                            className="shrink-0"
                        />
                    </div>

                    {!noSubChannels && subModeActive && (
                        <div className="mt-3 space-y-3">
                            {subRows.map((sub) => {
                                const isOpen = effectiveExpanded.has(sub.sub_channel_name);
                                return (
                                    <div
                                        key={sub.sub_channel_name}
                                        className="rounded-md border border-[#E5E6EB] bg-[#fbfbfb] transition-colors"
                                    >
                                        <button
                                            type="button"
                                            onClick={() => toggleExpand(sub.sub_channel_name)}
                                            className="flex w-full items-center justify-between px-4 py-3"
                                        >
                                            <span className="text-[14px] font-medium text-[#1D2129]">
                                                {sub.sub_channel_name}
                                            </span>
                                            {isOpen ? (
                                                <ChevronUp className="size-4 shrink-0 text-[#86909C]" />
                                            ) : (
                                                <ChevronDown className="size-4 shrink-0 text-[#86909C]" />
                                            )}
                                        </button>
                                        {isOpen && (
                                            <div className="space-y-1 px-2 pb-2">
                                                {sub.spaces.map((s) => (
                                                    <SyncSpaceItem
                                                        key={spaceKeyOf(s)}
                                                        space={s}
                                                        onDelete={() =>
                                                            deleteSubSpace(
                                                                sub.sub_channel_name,
                                                                spaceKeyOf(s),
                                                            )
                                                        }
                                                    />
                                                ))}
                                                <button
                                                    type="button"
                                                    onClick={() =>
                                                        handleAdd({
                                                            type: "sub",
                                                            subChannelName: sub.sub_channel_name,
                                                        })
                                                    }
                                                    className="flex w-full items-center gap-1.5 rounded-md px-2 py-2 text-[13px] text-[#4E5969] hover:bg-[#F7F8FA]"
                                                >
                                                    <PlusSquare className="size-3.5 shrink-0 text-gray-700" />
                                                    <span>
                                                        {localize?.(
                                                            "com_subscription.add_knowledge_space",
                                                        ) || "添加知识空间"}
                                                    </span>
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}

            <AddToKnowledgeModal
                open={modalOpen}
                onOpenChange={(v) => {
                    setModalOpen(v);
                    if (!v) setAddTarget(null);
                }}
                mode="channel_sync"
                onSyncSelect={handleSyncSelect}
                channelSyncPortalHostRef={knowledgePickerHostRef}
            />
        </div>
    );
}

/** Stable key for a draft space — the (space_id, folder_id) pair uniquely
 * identifies a binding since the spec only allows one folder per space. */
function spaceKeyOf(s: KnowledgeSyncSpaceItem): string {
    return `${s.knowledge_space_id}::${s.folder_id ?? ""}`;
}
