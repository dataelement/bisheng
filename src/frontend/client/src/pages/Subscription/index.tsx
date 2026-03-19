import { useLocalize } from "~/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
    Article,
    Channel,
    ChannelRole,
    SortType,
    createManagerChannelApi,
    updateChannelApi,
    getChannelDetailApi,
    getArticlesApi,
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
    const localize = useLocalize();
    const { channelId: previewChannelId } = useParams<{ channelId?: string }>();
    const navigate = useNavigate();
    const location = useLocation();
    const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
    const [channelRefreshToken, setChannelRefreshToken] = useState(0);
    const [showChannelSquare, setShowChannelSquare] = useState(false);
    const [showCreateChannelDrawer, setShowCreateChannelDrawer] = useState(false);
    const [fullScreenArticle, setFullScreenArticle] = useState<Article | null>(null);
    const [showAiAssistant, setShowAiAssistant] = useState(false);
    const [showFullScreenBtn, setShowFullScreenBtn] = useState(true);
    // Track whether fullscreen was entered via AI assistant button (not fullscreen button)
    const enteredFullscreenViaAiRef = useRef(false);
    const [previewDrawerOpen, setPreviewDrawerOpen] = useState(false);
    const [memberDialogOpen, setMemberDialogOpen] = useState(false);
    const [memberDialogSpace, setMemberDialogSpace] = useState<KnowledgeSpace | null>(null);
    const [channelMemberOpen, setChannelMemberOpen] = useState(false);
    const [channelMemberChannel, setChannelMemberChannel] = useState<Channel | null>(null);
    const [editingChannel, setEditingChannel] = useState<Channel | null>(null);
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    // Open preview drawer when channelId route param is present.
    // Prefetch data first to avoid showing a blank loading sheet (esp. private/dissolved channels).
    useEffect(() => {
        if (!previewChannelId) return;
        let cancelled = false;
        (async () => {
            try {
                await queryClient.prefetchQuery({
                    queryKey: ["channelPreviewDetail", previewChannelId],
                    queryFn: () => getChannelDetailApi(previewChannelId),
                    staleTime: 30_000,
                });
                await queryClient.prefetchQuery({
                    queryKey: ["channelPreviewArticles", previewChannelId],
                    queryFn: () =>
                        getArticlesApi({
                            channelId: previewChannelId,
                            page: 1,
                            pageSize: 10,
                        }),
                    staleTime: 30_000,
                });
                if (cancelled) return;
                setPreviewDrawerOpen(true);
            } catch {
                if (cancelled) return;
                showToast({
                    message: localize("com_subscription.channel_invalid_or_inaccessible"),
                    severity: NotificationSeverity.WARNING,
                });
                navigate("/channel?square=1", { replace: true });
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [previewChannelId]);

    // If navigation requests the channel square (e.g. via share-link error), open it.
    useEffect(() => {
        const params = new URLSearchParams(location.search);
        if (params.get("square") === "1") {
            setShowChannelSquare(true);
        }
    }, [location.search]);

    const handlePreviewDrawerClose = (open: boolean) => {
        setPreviewDrawerOpen(open);
        if (!open) {
            navigate("/channel", { replace: true });
        }
    };

    // Channel count is reported by ChannelSidebar via callback; ref avoids unnecessary re-renders
    const createdChannelCountRef = useRef(0);

    // Handle channel selection
    const handleChannelSelect = (channel: Channel | null) => {
        setActiveChannel(channel);
    };

    // Create channel - opens drawer (with limit check)
    const handleCreateChannel = () => {
        setEditingChannel(null);
        if (createdChannelCountRef.current >= MAX_USER_CHANNELS) {
            showToast({
                message: localize("com_subscription.channel_limit_reached"),
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
            // Refresh channel detail cache so ArticleList & tooltip pick up new settings
            await queryClient.invalidateQueries({ queryKey: ["channelDetail", editingChannel.id] });
            // Bump refresh token so ChannelLayout remounts and reloads articles
            setChannelRefreshToken(t => t + 1);
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
                <ChannelSquare
                    onBack={() => {
                        setShowChannelSquare(false);
                        navigate("/channel", { replace: true });
                    }}
                    onPreviewChannel={(id) => {
                        navigate(`/channel/share/${id}`);
                    }}
                />
            ) : (
                <>
                    {/* left sidebar */}
                    <ChannelSidebar
                        activeChannelId={activeChannel?.id}
                        onChannelSelect={handleChannelSelect}
                        onCreateChannel={handleCreateChannel}
                        onChannelSquare={handleChannelSquare}
                        onCreatedCountChange={(count) => { createdChannelCountRef.current = count; }}
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
                            key={`${activeChannel.id}-${channelRefreshToken}`}
                            channel={activeChannel}
                            onFullScreen={(article, ai) => {
                                enteredFullscreenViaAiRef.current = !!ai;
                                setFullScreenArticle(article);
                                setShowAiAssistant(ai || false);
                                setShowFullScreenBtn(!!ai);
                            }}
                        />
                    ) : (
                        <div className="flex flex-1 flex-col items-center justify-center py-10 text-center">
                            <img
                                className="size-[120px] mb-4 object-contain opacity-90"
                                src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                alt="empty"
                            />
                            <p className="text-[14px] leading-6 text-[#4E5969]">{localize("com_subscription.no_related_content_please")}<span
                                    className="ml-1.5 cursor-pointer text-[#165DFF] transition-colors hover:text-[#4080FF] active:text-[#0E42D2]"
                                    onClick={handleCreateChannel}
                                >{localize("com_subscription.create_channel")}</span>
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
                mode={editingChannel ? "edit" : "create"}
                editingChannel={editingChannel}
                onViewChannel={(channelId) => {
                    // 关闭创建抽屉
                    setShowCreateChannelDrawer(false);
                    // 尝试从已创建频道列表中找到新频道并设为当前激活
                    const createdList =
                        queryClient.getQueryData<Channel[]>(["channels", "created", SortType.RECENT_UPDATE]) || [];
                    const subscribedList =
                        queryClient.getQueryData<Channel[]>(["channels", "subscribed", SortType.RECENT_UPDATE]) || [];
                    const all = [...createdList, ...subscribedList];
                    const target = all.find((c) => c.id === channelId);
                    if (target) {
                        setActiveChannel(target);
                    }
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
                            enteredFullscreenViaAiRef.current = false;
                        }}
                        article={fullScreenArticle}
                        showFullScreenBtn={showFullScreenBtn}
                        onSwitchToFullScreen={() => {
                            // Close AI panel, transition to normal fullscreen mode
                            setShowAiAssistant(false);
                            setShowFullScreenBtn(false);
                            enteredFullscreenViaAiRef.current = false;
                        }}
                        showAiAssistant={showAiAssistant}
                        setShowAiAssistant={setShowAiAssistant}
                        onCloseAiAssistant={() => {
                            if (enteredFullscreenViaAiRef.current) {
                                // Entered fullscreen via AI button → exit fullscreen entirely
                                setFullScreenArticle(null);
                                setShowAiAssistant(false);
                                enteredFullscreenViaAiRef.current = false;
                            } else {
                                // Entered fullscreen first, then opened AI → just close AI panel
                                setShowAiAssistant(false);
                            }
                        }}
                    />
                </div>
            )}

            {/* Channel Preview Drawer (opened via share link route) */}
            <ChannelPreviewDrawer
                channelId={previewChannelId}
                open={previewDrawerOpen}
                onOpenChange={handlePreviewDrawerClose}
                onNavigateToChannel={(channelId) => {
                    // Find the channel from cached lists and auto-select it
                    const allChannels = [
                        ...(queryClient.getQueryData<Channel[]>(["channels", "created", SortType.RECENT_UPDATE]) || []),
                        // ...(queryClient.getQueryData<Channel[]>(["channels", "subscribed", SortType.RECENT_UPDATE]) || []),
                    ];
                    const found = allChannels.find(c => c.id === channelId);
                    if (found) {
                        setActiveChannel(found);
                    }
                    navigate("/channel", { replace: true });
                }}
            />
        </div>
    );
}
