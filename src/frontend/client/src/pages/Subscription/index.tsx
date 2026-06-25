import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useActivate, useUnactivate } from "react-activation";
import { useAuthContext } from "~/hooks/AuthContext";
import {
    Article,
    Channel,
    ChannelRole,
    SortType,
    createManagerChannelApi,
    updateChannelApi,
    getChannelDetailApi,
    getChannelsApi,
} from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { buildClientShareUrl } from "~/components/CopyShareLinkButton";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import ChannelSquare from "../ChannelSquare";
import { ChannelLayout } from "./ChannelLayout";
import { ChannelDiscoveryHome } from "./ChannelDiscoveryHome";
import { ChannelSquareTabs } from "./ChannelSquareTabs";
import { ChannelPreviewDrawer } from "./ChannelPreviewDrawer";
import FullScreenArticle from "./Article/FullScreenArticle";
import { ChannelSidebar } from "./Sidebar/ChannelSidebar";
import { CreateChannelDrawer } from "./CreateChannel/CreateChannelDrawer";
import type { CreateChannelFormData } from "./CreateChannel/CreateChannelDrawer";
import { buildCreateChannelPayload } from "./channelUtils";
import { createApiStatusError, extractApiStatusCode } from "./errorUtils";
import { Outlined } from "bisheng-icons";
import { useSetRecoilState, useRecoilValue } from "recoil";
import store from "~/store";
import { subscriptionDetailPaneWidthState } from "~/store/subscriptionLayout";
import { ChannelShareDialog } from "./ChannelShareDialog";
import { useEffectiveQuota } from "~/hooks/useEffectiveQuota";

const extractShareChannelIdFromPath = (pathname: string): string | undefined => {
    const matched = pathname.match(/\/channel\/share\/([^/?#]+)/);
    return matched?.[1];
};

// Detail-route channel id, parsed from the pathname (NOT useParams).
// Must stay consistent with `isShareRoute` (also pathname-derived): under react-activation
// KeepAlive, useParams() can return a stale channelId (e.g. a previously previewed share
// channel) after the tab is cached and restored, while location.pathname is already fresh.
// Reading both from the same source prevents that desync from synthesizing a bogus active channel.
const extractDetailChannelIdFromPath = (pathname: string): string | undefined => {
    const matched = pathname.match(/\/channel\/(?!share\/)([^/?#]+)/);
    return matched?.[1];
};

export default function Subscription() {
    const localize = useLocalize();
    const { user, isUserLoading } = useAuthContext();
    const navigate = useNavigate();
    const location = useLocation();
    const isShareRoute = location.pathname.includes("/channel/share/");
    const [shareChannelIdFromPath, setShareChannelIdFromPath] = useState<string | undefined>(
        extractShareChannelIdFromPath(location.pathname)
    );
    const [manualPreviewChannelId, setManualPreviewChannelId] = useState<string | undefined>(undefined);
    // Derive route ids from location.pathname only (never useParams): under react-activation
    // KeepAlive, useParams() can lag behind location after the tab is cached/restored.
    const routePreviewChannelId = shareChannelIdFromPath || (isShareRoute ? extractShareChannelIdFromPath(location.pathname) : undefined);
    const previewChannelId = routePreviewChannelId || manualPreviewChannelId;
    const detailChannelId = !isShareRoute ? extractDetailChannelIdFromPath(location.pathname) : undefined;
    const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
    const [channelRefreshToken, setChannelRefreshToken] = useState(0);
    const [showChannelSquare, setShowChannelSquare] = useState(false);
    const [showCreateChannelDrawer, setShowCreateChannelDrawer] = useState(false);
    const [fullScreenArticle, setFullScreenArticle] = useState<Article | null>(null);
    const [showAiAssistant, setShowAiAssistant] = useState(false);
    const [showFullScreenBtn, setShowFullScreenBtn] = useState(true);
    // Track whether fullscreen was entered via AI assistant button (not fullscreen button)
    const enteredFullscreenViaAiRef = useRef(false);
    /** When true, ignore stale async completion that would re-open the share preview (e.g. user closed overlay while user ref/effect re-ran). */
    const userClosedSharePreviewRef = useRef(false);
    const [previewDrawerOpen, setPreviewDrawerOpen] = useState(false);
    const [channelSquareRefreshKey, setChannelSquareRefreshKey] = useState(0);
    /** Bumped on KeepAlive re-activation so share-preview effect re-runs (deps may be unchanged vs cached instance). */
    const [channelTabActivateEpoch, setChannelTabActivateEpoch] = useState(0);
    const [channelPermissionDialogOpen, setChannelPermissionDialogOpen] = useState(false);
    const [channelPermissionDialogChannel, setChannelPermissionDialogChannel] = useState<Channel | null>(null);
    const isH5 = usePrefersMobileLayout();
    const [channelListDrawerOpen, setChannelListDrawerOpen] = useState(false);
    const [editingChannel, setEditingChannel] = useState<Channel | null>(null);
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();
    const setSystemMenuOpen = useSetRecoilState(store.mobileSystemMenuOpenState);
    // Right-area width (detail panel + splitter) published by ChannelLayout; offsets
    // the persistent 频道/广场 tab so it tracks the article-list column's right edge.
    const detailPaneWidth = useRecoilValue(subscriptionDetailPaneWidthState);
    const mobileHeadIconBtnClassName = "inline-flex size-8 items-center justify-center rounded-md text-[#212121] hover:bg-[#F7F8FA]";

    const openChannelPermissionDialog = (channel: Channel) => {
        setChannelPermissionDialogChannel(channel);
        setChannelPermissionDialogOpen(true);
    };

    const channelPluginGate = useMemo((): "loading" | "enabled" | "disabled" => {
        if (isUserLoading) return "loading";
        if (!user) return "enabled";
        const plugins = (user as { plugins?: unknown }).plugins;
        if (!Array.isArray(plugins)) return "enabled";
        return plugins.includes("subscription") ? "enabled" : "disabled";
    }, [user, isUserLoading]);

    // Keep parsed share channel id in sync with path (route params can lag on KeepAlive restore).
    useEffect(() => {
        setShareChannelIdFromPath(extractShareChannelIdFromPath(location.pathname));
    }, [location.pathname]);

    // Feature gate: system may disable Channel/Subscription via user plugins.
    // Share links should redirect to workbench home with a clear permission toast.
    useEffect(() => {
        if (channelPluginGate !== "disabled") return;
        showToast({
            message: localize("com_plugin_feature_no_access_toast"),
            severity: NotificationSeverity.ERROR,
        });
        navigate("/c/new", { replace: true });
    }, [channelPluginGate, showToast, navigate, localize]);

    // Route-driven sync for preview drawer:
    // manualPreviewChannelId (from plaza card click) opens drawer immediately.
    // routePreviewChannelId (from share link) waits for the creator check in the
    // validate-preview effect below — that effect calls setPreviewDrawerOpen(true)
    // only after confirming the user is NOT the creator, avoiding the open-then-close flash.
    useEffect(() => {
        if (manualPreviewChannelId) {
            userClosedSharePreviewRef.current = false;
            setPreviewDrawerOpen(true);
            return;
        }
        if (!routePreviewChannelId) {
            setPreviewDrawerOpen(false);
        }
    }, [routePreviewChannelId, manualPreviewChannelId, channelTabActivateEpoch]);

    // Validate preview channel when channelId route param is present.
    // Prefetch channel detail only (validates private / dissolved). Articles load inside
    // ChannelPreviewDrawer so a list API failure does not close the share route and bounce to square.
    // Creator shortcut: skip drawer only when not browsing channel plaza (plaza card click should
    // always open the same preview as other subscribers).
    const previewUserKey = user?.username ?? "";

    useEffect(() => {
        if (!previewChannelId || !user) return;
        if (channelPluginGate === "loading" || channelPluginGate === "disabled") return;
        userClosedSharePreviewRef.current = false;
        let cancelled = false;
        (async () => {
            try {
                const detail: any = await queryClient.fetchQuery({
                    queryKey: ["channelPreviewDetail", previewChannelId],
                    queryFn: async () => {
                        const res: any = await getChannelDetailApi(previewChannelId);
                        const payload =
                            res?.id != null && String(res.id) !== ""
                                ? res
                                : res?.data && typeof res.data === "object"
                                    ? res.data
                                    : res;
                        if (!payload?.id) {
                            throw new Error("channel_invalid");
                        }
                        if (payload?.status_code && payload.status_code !== 200) {
                            throw new Error("channel_invalid");
                        }
                        return payload;
                    },
                    staleTime: 0,
                    retry: false,
                });

                if (cancelled) return;

                const isCreator =
                    Boolean(user?.username) &&
                    Boolean(detail?.creator_name) &&
                    String(user.username).trim() === String(detail.creator_name).trim();

                // Share link guard: if the channel has become private (or otherwise inaccessible),
                // show toast and redirect to channel square. Skip for the channel creator.
                if (detail?.visibility === "private" && !isCreator) {
                    showToast({
                        message: localize("com_subscription.channel_invalid_or_inaccessible"),
                        severity: NotificationSeverity.WARNING,
                    });
                    navigate("/channel?square=1", { replace: true });
                    return;
                }

                // From channel square: always show preview (even for creator). Direct share links
                // paste/open: keep shortcut into main channel UI.
                // Use ?square=1 (not React state): navigating /channel → /channel/share/* can remount
                // Subscription and reset showChannelSquare, which wrongly triggered the creator shortcut.
                const fromChannelSquare =
                    new URLSearchParams(location.search).get("square") === "1";
                if (isCreator && !fromChannelSquare) {
                    const allChannels = [
                        ...(queryClient.getQueryData<Channel[]>(["channels", "created", SortType.RECENT_UPDATE]) || []),
                    ];
                    const found = allChannels.find(c => c.id === previewChannelId);
                    setActiveChannel(found ?? {
                        id: String(previewChannelId),
                        name: String(detail?.name ?? ""),
                        description: detail?.description,
                        creator: detail?.creator_name ?? "",
                        creatorId: "",
                        subscriberCount: Number(detail?.subscriber_count ?? 0),
                        articleCount: Number(detail?.article_count ?? 0),
                        unreadCount: 0,
                        role: ChannelRole.MEMBER,
                        isPinned: false,
                        createdAt: String(detail?.create_time ?? ""),
                        updatedAt: String(detail?.latest_article_update_time ?? ""),
                        subChannels: [],
                        source_list: detail?.source_list ?? [],
                    });
                    navigate("/channel", { replace: true });
                    return;
                }

                if (cancelled) return;
                if (userClosedSharePreviewRef.current) return;
                // Not the creator — open preview drawer now (deferred to avoid flash
                // when the creator shortcut would immediately close it).
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
    }, [previewChannelId, previewUserKey, location.search, channelTabActivateEpoch, channelPluginGate, localize, navigate, queryClient, showToast, user]);

    // Leaving /channel/share/* should not leave the drawer marked open with a stale channelId.
    useEffect(() => {
        if (!previewChannelId) {
            setPreviewDrawerOpen(false);
        }
    }, [previewChannelId]);

    // Deep link to channel detail: /channel/:channelId
    useEffect(() => {
        if (!detailChannelId) return;
        if (channelPluginGate === "loading" || channelPluginGate === "disabled") return;
        let cancelled = false;
        (async () => {
            try {
                const detail: any = await getChannelDetailApi(detailChannelId);
                if (cancelled) return;
                const name = String(detail?.name ?? "");
                setActiveChannel({
                    id: String(detailChannelId),
                    name,
                    description: detail?.description,
                    creator: detail?.creator_name ?? "",
                    creatorId: "",
                    subscriberCount: Number(detail?.subscriber_count ?? 0),
                    articleCount: Number(detail?.article_count ?? 0),
                    unreadCount: 0,
                    role: ChannelRole.MEMBER,
                    isPinned: false,
                    createdAt: String(detail?.create_time ?? ""),
                    updatedAt: String(detail?.latest_article_update_time ?? ""),
                    subChannels: [],
                    source_list: detail?.source_list ?? [],
                });
            } catch {
                // Fallback: land on channel page; user can select manually
                navigate("/channel", { replace: true });
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [detailChannelId, channelPluginGate, navigate]);

    // If navigation requests the channel square (e.g. via share-link error), open it.
    useEffect(() => {
        if (channelPluginGate === "loading" || channelPluginGate === "disabled") return;
        const params = new URLSearchParams(location.search);
        const inSquare = params.get("square") === "1";
        const path = location.pathname || "";
        if (inSquare) {
            console.info("[Subscription] route indicates square mode", { path, search: location.search });
            setShowChannelSquare(true);
            return;
        }
        // Keep state aligned with URL: when navigating to /channel/:id from notifications,
        // ensure we exit plaza mode so detail page can render.
        if (/\/channel\/[^/]+/.test(path) && !path.includes("/channel/share/")) {
            console.info("[Subscription] route indicates detail mode", { path, search: location.search });
            setShowChannelSquare(false);
        }
    }, [location.search, location.pathname, channelPluginGate]);

    // KeepAlive: when leaving /channel, component is "deactivated" (effects may not run).
    // Reset square view so switching back lands on default channel page.
    useUnactivate(() => {
        setShowChannelSquare(false);
    });

    // KeepAlive: when coming back to the channel tab, `location` deps may be unchanged so effects
    // that open the plaza / share preview do not re-run. Sync from URL and force preview effect.
    useActivate(() => {
        const path = window.location.pathname;
        const params = new URLSearchParams(window.location.search);
        setShareChannelIdFromPath(extractShareChannelIdFromPath(path));
        if (params.get("square") === "1") {
            setShowChannelSquare(true);
        }
        if (path.includes("/channel/share/")) {
            setChannelTabActivateEpoch((e) => e + 1);
        }
    });

    const handlePreviewDrawerClose = (open: boolean) => {
        setPreviewDrawerOpen(open);
        if (!open) {
            setManualPreviewChannelId(undefined);
            userClosedSharePreviewRef.current = true;
            // Keep URL aligned with plaza mode so search/effects don't fight; avoid refreshKey bump here
            // (it remounts the list and feels like the page "jumping"; subscribe still bumps via bumpChannelSquareList).
            const backToSquare =
                new URLSearchParams(location.search).get("square") === "1";
            navigate(backToSquare ? "/channel?square=1" : "/channel", { replace: true });
        }
    };

    const bumpChannelSquareList = () => setChannelSquareRefreshKey((k) => k + 1);

    // Stable callbacks for the memo'd ChannelSquare — prevents the card list
    // from re-rendering (flashing) when navigate() re-renders Subscription on
    // card click.
    const handleSquareBack = useCallback(() => {
        setShowChannelSquare(false);
        navigate("/channel", { replace: true });
    }, [navigate]);

    const handleSquarePreview = useCallback((id: string) => {
        // Open the preview drawer purely from React state — do NOT navigate to
        // /channel/share/:id. That path is a SEPARATE route entry, so routing
        // to it unmounts/remounts the whole Subscription page (showChannelSquare
        // resets to false then back to true), producing a visible flash. The
        // drawer opens from manualPreviewChannelId; the URL stays at
        // /channel?square=1. Share links are still generated by the drawer's
        // own share button, which targets /channel/share/:id directly.
        setManualPreviewChannelId(id);
        userClosedSharePreviewRef.current = false;
        setPreviewDrawerOpen(true);
    }, []);

    // Channel count is reported by ChannelSidebar (H5 drawer) via callback; ref avoids unnecessary re-renders
    const createdChannelCountRef = useRef(0);
    const { isOverQuota } = useEffectiveQuota();

    // Page owns channel list + auto-select on both PC and H5 so the page lands on a real channel
    // by default. Channel switching UI is route-driven (system menu reveal on H5).
    const channelPluginEnabled = channelPluginGate === "enabled";
    const { data: createdChannelsForAuto = [], isFetched: createdAutoFetched } = useQuery({
        queryKey: ["channels", "created", SortType.RECENT_UPDATE],
        queryFn: () => getChannelsApi({ type: "created", sortBy: SortType.RECENT_UPDATE }),
        enabled: channelPluginEnabled,
        placeholderData: (prev) => prev,
    });
    const { data: subscribedChannelsForAuto = [], isFetched: subscribedAutoFetched } = useQuery({
        queryKey: ["channels", "subscribed", SortType.RECENT_UPDATE],
        queryFn: () => getChannelsApi({ type: "subscribed", sortBy: SortType.RECENT_UPDATE }),
        enabled: channelPluginEnabled,
        placeholderData: (prev) => prev,
    });

    // True while we still can't tell whether the user has channels: the plugin
    // gate is resolving, or the channel lists haven't finished their first fetch.
    // Drives a loading view so the "no channels, create one" empty state never
    // flashes before auto-select can land on a real channel.
    const channelsResolving =
        channelPluginGate === "loading" ||
        (channelPluginEnabled && (!createdAutoFetched || !subscribedAutoFetched));

    useEffect(() => {
        createdChannelCountRef.current = createdChannelsForAuto.length;
    }, [createdChannelsForAuto.length]);

    // Auto-select first channel when nothing is active (skip while a share/preview is resolving).
    useEffect(() => {
        if (!channelPluginEnabled) return;
        if (activeChannel || previewChannelId || showChannelSquare) return;
        if (!createdAutoFetched || !subscribedAutoFetched) return;
        if (createdChannelsForAuto.length > 0) {
            setActiveChannel(createdChannelsForAuto[0]);
        } else if (subscribedChannelsForAuto.length > 0) {
            setActiveChannel(subscribedChannelsForAuto[0]);
        }
    }, [channelPluginEnabled, activeChannel, previewChannelId, showChannelSquare, createdAutoFetched, subscribedAutoFetched, createdChannelsForAuto, subscribedChannelsForAuto]);

    useEffect(() => {
        if (!isH5) setChannelListDrawerOpen(false);
    }, [isH5]);

    // Handle channel selection
    const handleChannelSelect = (channel: Channel | null) => {
        setActiveChannel(channel);
        if (isH5) setChannelListDrawerOpen(false);
    };

    // Create channel - opens drawer (with limit check)
    const handleCreateChannel = () => {
        setEditingChannel(null);
        if (isOverQuota("channel", createdChannelCountRef.current)) {
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
            const response = await updateChannelApi(editingChannel.id, payload);
            const updateCode = extractApiStatusCode(response);
            if (updateCode && updateCode !== 200) {
                throw createApiStatusError(response);
            }
            await queryClient.invalidateQueries({ queryKey: ["channels"] });
            // Refresh channel detail cache so ArticleList & tooltip pick up new settings
            await queryClient.invalidateQueries({ queryKey: ["channelDetail", editingChannel.id] });
            // Bump refresh token so ChannelLayout remounts and reloads articles
            setChannelRefreshToken(t => t + 1);
            return { channelId: editingChannel.id };
        }

        // 创建模式：POST /api/v1/channel/manager/create
        const res: any = await createManagerChannelApi(payload);
        const createCode = extractApiStatusCode(res);
        if (createCode && createCode !== 200) {
            throw createApiStatusError(res);
        }
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

    if (channelPluginGate === "disabled") {
        return null;
    }

    return (
        <div className="relative flex min-h-0 flex-1 flex-col touch-desktop:flex-row">
            {/* 频道 / 广场 切换 — 提升到两个视图之上常驻，切换时同一滑块平滑移动，
                位置与频道页标题行右上（pt-5 / px-10）对齐。仅 PC。 */}
            {!isH5 && (activeChannel || showChannelSquare) ? (
                <div className="absolute top-5 z-20" style={{ right: `${detailPaneWidth + 40}px` }}>
                    <ChannelSquareTabs
                        active={showChannelSquare ? "square" : "channel"}
                        onChannelClick={handleSquareBack}
                        onSquareClick={handleChannelSquare}
                    />
                </div>
            ) : null}
            {showChannelSquare ? (
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                    <ChannelSquare
                        refreshKey={channelSquareRefreshKey}
                        onPreviewChannel={handleSquarePreview}
                    />
                </div>
            ) : (
                <>
                    {/* PC：频道列表已移至顶部标题下拉（ChannelSwitcher）；H5：改抽屉叠在主内容之上（见下方 fixed） */}
                    {isH5 && channelListDrawerOpen ? (
                        <div
                            className="fixed inset-0 z-[70] flex"
                            role="dialog"
                            aria-modal="true"
                            aria-label={localize("com_subscription.subscribe")}
                        >
                            <div className="flex h-full w-[240px] max-w-[240px] shrink-0 flex-col overflow-hidden bg-white shadow-[4px_0_24px_rgba(0,0,0,0.06)] pt-[env(safe-area-inset-top,0px)]">
                                <ChannelSidebar
                                    mobileDrawerMode
                                    onDrawerClose={() => setChannelListDrawerOpen(false)}
                                    activeChannelId={activeChannel?.id}
                                    suppressAutoSelect={!!previewChannelId}
                                    onChannelSelect={handleChannelSelect}
                                    onCreateChannel={handleCreateChannel}
                                    onChannelSquare={handleChannelSquare}
                                    onCreatedCountChange={(count) => { createdChannelCountRef.current = count; }}
                                    onManageMembers={(channel) => {
                                        setChannelListDrawerOpen(false);
                                        openChannelPermissionDialog(channel);
                                    }}
                                    onChannelSettings={(channel) => {
                                        setChannelListDrawerOpen(false);
                                        setEditingChannel(null);
                                        (async () => {
                                            try {
                                                const detail = await getChannelDetailApi(channel.id);
                                                setEditingChannel({ ...channel, ...detail });
                                            } catch {
                                                setEditingChannel(channel);
                                            } finally {
                                                setShowCreateChannelDrawer(true);
                                            }
                                        })();
                                    }}
                                />
                            </div>
                            <button
                                type="button"
                                className="min-w-0 flex-1 bg-[rgba(86,88,105,0.55)]"
                                aria-label={localize("com_nav_close_sidebar")}
                                onClick={() => setChannelListDrawerOpen(false)}
                            />
                        </div>
                    ) : null}

                    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                        {activeChannel ? (
                            <ChannelLayout
                                key={`${activeChannel.id}-${channelRefreshToken}`}
                                channel={activeChannel}
                                onChannelSelect={handleChannelSelect}
                                onManageMembers={(channel) => openChannelPermissionDialog(channel)}
                                onChannelSettings={(channel) => {
                                    setEditingChannel(null);
                                    (async () => {
                                        try {
                                            const detail = await getChannelDetailApi(channel.id);
                                            setEditingChannel({ ...channel, ...detail });
                                        } catch {
                                            setEditingChannel(channel);
                                        } finally {
                                            setShowCreateChannelDrawer(true);
                                        }
                                    })();
                                }}
                                onOpenChannelNav={isH5 ? () => setSystemMenuOpen(true) : undefined}
                                onGoChannelSquare={handleChannelSquare}
                                onCreateChannel={handleCreateChannel}
                                onFullScreen={(article, ai) => {
                                    // 全屏 button (ai === false): open the standalone article page in a new tab.
                                    // AI assistant button (ai === true): keep the existing in-app fullscreen overlay
                                    // so the assistant panel can dock alongside the article.
                                    if (!ai) {
                                        const url = buildClientShareUrl(`/channel/${article.channelId}/article/${article.id}`);
                                        window.open(url, "_blank", "noopener,noreferrer");
                                        return;
                                    }
                                    enteredFullscreenViaAiRef.current = true;
                                    setFullScreenArticle(article);
                                    setShowAiAssistant(true);
                                    setShowFullScreenBtn(true);
                                }}
                            />
                        ) : channelsResolving ? (
                            <div className="relative flex flex-1 flex-col items-center justify-center py-10 text-center text-[#86909c]">
                                {isH5 ? (
                                    <div className="absolute inset-x-0 top-0 z-10 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
                                        {/* Match the loaded ArticleList header: safe-area+8px top
                                            padding on the wrapper, a separate h-11 row, size-5 icon. */}
                                        <div className="relative flex h-11 items-center px-4">
                                            <button
                                                type="button"
                                                aria-label={localize("com_nav_open_sidebar")}
                                                onClick={() => setSystemMenuOpen(true)}
                                                className={mobileHeadIconBtnClassName}
                                            >
                                                <Outlined.SidebarMenu className="size-5" />
                                            </button>
                                            <h1 className="pointer-events-none absolute left-1/2 -translate-x-1/2 text-[16px] font-medium leading-6 text-[#212121]">
                                                {localize("com_subscription.subscribe")}
                                            </h1>
                                        </div>
                                    </div>
                                ) : null}
                                <LoadingIcon className="size-20 text-primary" />
                            </div>
                        ) : (
                            <ChannelDiscoveryHome
                                enabled
                                isH5={isH5}
                                onOpenMobileNav={() => setSystemMenuOpen(true)}
                                onPreviewChannel={handleSquarePreview}
                                onGoSquare={handleChannelSquare}
                                onCreateChannel={handleCreateChannel}
                            />
                        )}
                    </div>
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
                    openChannelPermissionDialog({
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
                }}
            />

            <ChannelShareDialog
                open={channelPermissionDialogOpen}
                onOpenChange={setChannelPermissionDialogOpen}
                channel={channelPermissionDialogChannel}
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
                                // H5：从 AI 返回正文全屏层，不直接关回列表；大屏：经 AI 进入则整页退出
                                if (isH5) {
                                    setShowAiAssistant(false);
                                    return;
                                }
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
                onSubscriptionChanged={bumpChannelSquareList}
            />
        </div>
    );
}
