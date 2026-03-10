import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
    Article,
    Channel,
    ChannelRole,
    getChannelsApi,
    SortType,
    createManagerChannelApi,
    updateChannelApi,
    getChannelDetailApi,
} from "~/api/channels";
import { type KnowledgeSpace } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { KnowledgeSpaceMemberDialog } from "~/components/KnowledgeSpaceMemberDialog";
import { ChannelMemberDialog } from "~/components/ChannelMemberDialog";
import ChannelSquare from "../ChannelSquare";
import { ChannelLayout } from "./ChannelLayout";
import { ChannelPreviewDrawer } from "./ChannelPreviewDrawer";
import FullScreenArticle from "./Article/FullScreenArticle";
import { ChannelSidebar } from "./Sidebar/ChannelSidebar";
import { CreateChannelDrawer } from "./CreateChannel/CreateChannelDrawer";
import type { CreateChannelFormData } from "./CreateChannel/CreateChannelDrawer";
import { buildCreateChannelPayload } from "./channelUtils";

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
    const [channelMemberOpen, setChannelMemberOpen] = useState(false);
    const [channelMemberChannel, setChannelMemberChannel] = useState<Channel | null>(null);
    const [editingChannel, setEditingChannel] = useState<Channel | null>(null);
    const { showToast } = useToastContext();
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
        setEditingChannel(null);
        if (createdChannelCount >= MAX_USER_CHANNELS) {
            showToast({
                message: "您已达到创建频道数量的最大上限",
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        setShowCreateChannelDrawer(true);
    };

    const handleCreateChannelConfirm = async (data: CreateChannelFormData): Promise<{ channelId: string }> => {
        const payload = buildCreateChannelPayload(data);

        // 编辑模式：使用 PUT /api/v1/channel/manager/{channel_id}，保证权限设置、内容筛选、子频道等一起更新
        if (editingChannel) {
            await updateChannelApi(editingChannel.id, payload);
            await queryClient.invalidateQueries({ queryKey: ["channels"] });
            return { channelId: editingChannel.id };
        }

        // 创建模式：POST /api/v1/channel/manager/create
        const res: any = await createManagerChannelApi(payload);
        await queryClient.invalidateQueries({ queryKey: ["channels"] });
        const root = res?.data ?? res;
        const payloadRes = root?.data ?? root;
        const channelId = String(
            payloadRes?.id ??
            payloadRes?.channel_id ??
            payloadRes?.data?.id ??
            payloadRes?.data?.channel_id ??
            ""
        );
        if (!channelId) throw new Error("missing channel id");
        return { channelId };
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
                        onManageMembers={(channel) => {
                            setChannelMemberChannel(channel);
                            setChannelMemberOpen(true);
                        }}
                        onChannelSettings={(channel) => {
                            // 打开抽屉 + 用详情接口回显
                            setShowCreateChannelDrawer(true);
                            setEditingChannel(null);
                            (async () => {
                                try {
                                    const detail = await getChannelDetailApi(channel.id);
                                    // 以 /my_channels 的列表项为基础，叠加详情字段（description / visibility / is_released / source_list 等）
                                    setEditingChannel({ ...channel, ...detail });
                                } catch {
                                    // 如果详情接口失败，至少保证能用列表里的基础字段编辑名称
                                    setEditingChannel(channel);
                                }
                            })();
                        }}
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
                mode={editingChannel ? "edit" : "create"}
                editingChannel={editingChannel}
                onViewChannel={() => {
                    // 预留：后续可跳转到新建频道
                }}
                onManageMembers={(channelId) => {
                    setChannelMemberChannel({
                        id: channelId,
                        name: "",
                        creator: "",
                        creatorId: "",
                        subscriberCount: 0,
                        articleCount: 0,
                        unreadCount: 0,
                        role: ChannelRole.CREATOR,
                        isPinned: false,
                        createdAt: "",
                        updatedAt: "",
                        subChannels: []
                    });
                    setChannelMemberOpen(true);
                }}
            />

            <KnowledgeSpaceMemberDialog
                open={memberDialogOpen}
                onOpenChange={setMemberDialogOpen}
                space={memberDialogSpace}
            />

            <ChannelMemberDialog
                open={channelMemberOpen}
                onOpenChange={setChannelMemberOpen}
                channelId={channelMemberChannel?.id || null}
                currentUserRole={channelMemberChannel?.role || null}
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
