import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
    Article,
    Channel,
    getChannelsApi,
    SortType,
    createManagerChannelApi,
    type CreateManagerChannelPayload,
    type ManagerChannelFilterRule,
    type ManagerChannelRuleItem
} from "~/api/channels";
import { type KnowledgeSpace, SpaceRole, VisibilityType } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import { KnowledgeSpaceMemberDialog } from "~/components/KnowledgeSpaceMemberDialog";
import ChannelSquare from "../ChannelSquare";
import { ChannelLayout } from "./ChannelLayout";
import { ChannelPreviewDrawer } from "./ChannelPreviewDrawer";
import FullScreenArticle from "./Article/FullScreenArticle";
import { ChannelSidebar } from "./sidebar/ChannelSidebar";
import { CreateChannelDrawer } from "./CreateChannelDrawer";
import type { CreateChannelFormData } from "./CreateChannelDrawer";

const MAX_USER_CHANNELS = 10;

export default function Subscription() {
    const { channelId: previewChannelId } = useParams<{ channelId?: string }>();
    const navigate = useNavigate();
    const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
    const [showChannelSquare, setShowChannelSquare] = useState(false);
    const [showCreateChannelDrawer, setShowCreateChannelDrawer] = useState(false);
    const [fullScreenArticle, setFullScreenArticle] = useState<Article | null>(null);
    const [showAiAssistant, setShowAiAssistant] = useState(false);
    const [previewDrawerOpen, setPreviewDrawerOpen] = useState(false);
    const [memberDialogOpen, setMemberDialogOpen] = useState(false);
    const [memberDialogSpace, setMemberDialogSpace] = useState<KnowledgeSpace | null>(null);
    const { showToast } = useToastContext();
    const localize = useLocalize();
    const queryClient = useQueryClient();

    // Open preview drawer when channelId route param is present
    useEffect(() => {
        if (previewChannelId) {
            setPreviewDrawerOpen(true);
        }
    }, [previewChannelId]);

    const handlePreviewDrawerClose = (open: boolean) => {
        setPreviewDrawerOpen(open);
        if (!open) {
            navigate("/channel", { replace: true });
        }
    };

    const { data: createdChannels = [] } = useQuery({
        queryKey: ["channels", "created", SortType.RECENT_UPDATE],
        queryFn: () => getChannelsApi({ type: "created", sortBy: SortType.RECENT_UPDATE })
    });
    const createdChannelCount = createdChannels.length;

    // Handle channel selection
    const handleChannelSelect = (channel: Channel | null) => {
        setActiveChannel(channel);
    };

    // Create channel - opens drawer (with limit check)
    const handleCreateChannel = () => {
        if (createdChannelCount >= MAX_USER_CHANNELS) {
            showToast({
                message: "您已达到创建频道数量的最大上限",
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        setShowCreateChannelDrawer(true);
    };

    const handleCreateChannelConfirm = async (data: CreateChannelFormData) => {
        try {
            const buildFilterRules = (): ManagerChannelFilterRule[] => {
                if (!data.contentFilter || !data.filterGroups.length) return [];
                const groups = data.filterGroups;
                return groups.map((group): ManagerChannelFilterRule => {
                    const rules: ManagerChannelRuleItem[] = group.conditions.map((cond) => {
                        const keywords =
                            cond.keywords
                                ?.split(/[;；]/)
                                .map((k: string) => k.trim())
                                .filter(Boolean) || [];
                        return {
                            rule_type: cond.include ? "include" : "exclude",
                            keywords
                        };
                    });
                    return {
                        rules,
                        relation: group.relation
                    };
                });
            };

            const payload: CreateManagerChannelPayload = {
                name: data.channelName.trim(),
                source_list: data.sources.map((s) => s.id),
                visibility: data.visibility,
                filter_rules: buildFilterRules(),
                is_released: data.publishToSquare === "yes"
            };

            await createManagerChannelApi(payload);
            await queryClient.invalidateQueries({ queryKey: ["channels"] });
            showToast({
                message: localize("channel_created") || "频道创建成功",
                severity: NotificationSeverity.SUCCESS
            });
        } catch (e) {
            showToast({
                message: localize("channel_create_failed") || "频道创建失败，请稍后重试",
                severity: NotificationSeverity.ERROR
            });
        }
    };

    const toMemberDialogSpace = (channel?: Channel | null): KnowledgeSpace => {
        const c = channel || activeChannel || createdChannels[0];
        if (c) {
            return {
                id: c.id,
                name: c.name,
                description: c.description || "",
                visibility: VisibilityType.PUBLIC,
                creator: c.creator,
                creatorId: c.creatorId,
                memberCount: c.subscriberCount || 0,
                fileCount: 0,
                totalFileCount: 0,
                role: c.role as unknown as SpaceRole,
                isPinned: c.isPinned,
                createdAt: c.createdAt,
                updatedAt: c.updatedAt,
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
    };

    // Channel square
    const handleChannelSquare = () => {
        setShowChannelSquare(true);
    };

    // Esc to exit full screen
    useEffect(() => {
        if (!fullScreenArticle) return;
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") setFullScreenArticle(null);
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [fullScreenArticle]);

    return (
        <div className="relative h-full flex">
            {showChannelSquare ? (
                <ChannelSquare onBack={() => setShowChannelSquare(false)} />
            ) : (
                <>
                    {/* left sidebar */}
                    <ChannelSidebar
                        activeChannelId={activeChannel?.id}
                        onChannelSelect={handleChannelSelect}
                        onCreateChannel={handleCreateChannel}
                        onChannelSquare={handleChannelSquare}
                    />

                    {activeChannel ? (
                        <ChannelLayout
                            channel={activeChannel}
                            onFullScreen={(article, ai) => {
                                setFullScreenArticle(article);
                                setShowAiAssistant(ai || false);
                            }}
                        />
                    ) : (
                        <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
                            <img
                                className="size-[120px] mb-4 object-contain opacity-90"
                                src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                alt="empty"
                            />
                            <p className="text-[14px] leading-6 text-[#4E5969]">
                                无相关内容，请
                                <span
                                    className="ml-1.5 cursor-pointer text-[#165DFF] transition-colors hover:text-[#4080FF] active:text-[#0E42D2]"
                                    onClick={handleCreateChannel}
                                >
                                    创建频道
                                </span>
                            </p>
                        </div>
                    )}
                </>
            )}

            {/* 创建频道抽屉 */}
            <CreateChannelDrawer
                open={showCreateChannelDrawer}
                onOpenChange={setShowCreateChannelDrawer}
                onConfirm={handleCreateChannelConfirm}
                createdChannelCount={createdChannelCount}
                onViewChannel={() => {
                    // 预留：后续可跳转到新建频道
                }}
                onManageMembers={() => {
                    setMemberDialogSpace(toMemberDialogSpace());
                    setMemberDialogOpen(true);
                }}
            />

            <KnowledgeSpaceMemberDialog
                open={memberDialogOpen}
                onOpenChange={setMemberDialogOpen}
                space={memberDialogSpace}
            />

            {/* Full-screen overlay — absolute inset-0 covers the entire Subscription (including the channel sidebar), but doesn't affect MainLayout's primary navigation */}
            {fullScreenArticle && (
                <div className="absolute inset-0 z-50 bg-white flex flex-col h-full">
                    <FullScreenArticle
                        onExit={() => {
                            setFullScreenArticle(null);
                            setShowAiAssistant(false);
                        }}
                        article={fullScreenArticle}
                        showAiAssistant={showAiAssistant}
                        setShowAiAssistant={setShowAiAssistant}
                    />
                </div>
            )}

            {/* Channel Preview Drawer (opened via share link route) */}
            <ChannelPreviewDrawer
                channelId={previewChannelId}
                open={previewDrawerOpen}
                onOpenChange={handlePreviewDrawerClose}
            />
        </div>
    );
}
