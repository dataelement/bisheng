import { ApiRequestFailure } from "~/components/ApiRequestFailure";
import { useChannelLists } from "./hooks/useChannelLists";
import {
  refreshChannelState,
  useChannelAccessGuard,
  useChannelStateRefresh,
} from "./hooks/useChannelStateRefresh";
import { useLocalize, usePrefersMobileLayout } from "~/hooks";
import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useActivate, useUnactivate } from "react-activation";
import { useAuthContext } from "~/hooks/AuthContext";
import { Article, Channel, ChannelRole, SortType, getChannelDetailApi } from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { buildClientShareUrl } from "~/components/CopyShareLinkButton";
import { SubscriptionArticleOverlay, SubscriptionLoadingView } from "./SubscriptionViews";
import ChannelSquare from "../ChannelSquare";
import { ChannelLayout } from "./ChannelLayout";
import { ChannelDiscoveryHome } from "./ChannelDiscoveryHome";
import { ChannelHomePage } from "./ChannelHomePage";
import { isDemoId } from "~/mock/demo/ids";
import { ChannelPreviewDrawer } from "./ChannelPreviewDrawer";
import { canReadChannelContent } from "./channelContentAccess";
import { Button, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useSetRecoilState } from "recoil";
import store from "~/store";
import { useEffectiveQuota } from "~/hooks/useEffectiveQuota";
import { squareTypePath } from "~/pages/square/squarePaths";

import { extractDetailChannelIdFromPath, extractShareChannelIdFromPath } from "./subscriptionPaths";

export default function Subscription() {
  const localize = useLocalize();
  const { user, isUserLoading } = useAuthContext();
  const navigate = useNavigate();
  const location = useLocation();
  const isShareRoute = location.pathname.includes("/channel/share/");
  const [shareChannelIdFromPath, setShareChannelIdFromPath] = useState<string | undefined>(
    extractShareChannelIdFromPath(location.pathname),
  );
  const [manualPreviewChannelId, setManualPreviewChannelId] = useState<string | undefined>(undefined);
  // Derive route ids from location.pathname only (never useParams): under react-activation
  // KeepAlive, useParams() can lag behind location after the tab is cached/restored.
  const routePreviewChannelId =
    shareChannelIdFromPath || (isShareRoute ? extractShareChannelIdFromPath(location.pathname) : undefined);
  const previewChannelId = routePreviewChannelId || manualPreviewChannelId;
  const detailChannelId = !isShareRoute ? extractDetailChannelIdFromPath(location.pathname) : undefined;
  const [activeChannel, setActiveChannel] = useState<Channel | null>(null);
  const [channelRefreshToken] = useState(0);
  const [showChannelSquare, setShowChannelSquare] = useState(false);
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
  const isH5 = usePrefersMobileLayout();
  const { showToast } = useToastContext();
  const queryClient = useQueryClient();
  const setSystemMenuOpen = useSetRecoilState(store.mobileSystemMenuOpenState);

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
      severity: NotificationSeverity.WARNING,
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
        const fromChannelSquare = new URLSearchParams(location.search).get("square") === "1";
        if (isCreator && !fromChannelSquare) {
          const allChannels = [
            ...(queryClient.getQueryData<Channel[]>(["channels", "created", SortType.RECENT_UPDATE]) || []),
          ];
          const found = allChannels.find((c) => c.id === previewChannelId);
          setActiveChannel(
            found ?? {
              id: String(previewChannelId),
              name: String(detail?.name ?? ""),
              description: detail?.description,
              creator: detail?.creator_name ?? "",
              creatorId: "",
              subscriberCount: Number(detail?.subscriber_count ?? 0),
              articleCount: Number(detail?.article_count ?? 0),
              unreadCount: 0,
              role: ChannelRole.MEMBER,
              actions: detail?.actions,
              isPinned: false,
              createdAt: String(detail?.create_time ?? ""),
              updatedAt: String(detail?.latest_article_update_time ?? ""),
              subChannels: [],
              source_list: detail?.source_list ?? [],
            },
          );
          navigate(`/channel/${encodeURIComponent(previewChannelId)}`, { replace: true });
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
  }, [
    previewChannelId,
    previewUserKey,
    location.search,
    channelTabActivateEpoch,
    channelPluginGate,
    localize,
    navigate,
    queryClient,
    showToast,
    user,
  ]);

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
        // Membership is decided here, at open time — not by whoever sent the link.
        // A former member following an old notification, or anyone with the id,
        // gets the same intro-and-apply preview the square shows; only an active
        // subscriber, or someone the F048 catalog makes the channel `visible` to,
        // enters the channel itself. `visible` is the very decision the article
        // endpoint re-checks, so the page and the API agree.
        //
        const subscribed = String(detail?.subscription_status ?? "").toLowerCase() === "subscribed";
        if (!canReadChannelContent({ actions: detail?.actions, isSubscribed: subscribed })) {
          // Nothing to show and nowhere to apply: the channel was never published to
          // the square, so there is no intro page for a stranger to land on. Say so and
          // leave them on the square, the way an invalid knowledge-space link behaves.
          if (!detail?.is_released) {
            showToast({
              message: localize("com_subscription.channel_unavailable_or_no_permission"),
              severity: NotificationSeverity.WARNING,
            });
            navigate("/channel?square=1", { replace: true });
            return;
          }
          // Published: the share route shows the intro-and-apply preview. Deliberately
          // without ?square=1 — that flag means "arrived from the square" and would both
          // render the square behind the preview and send the user there on close.
          navigate(`/channel/share/${detailChannelId}`, { replace: true });
          return;
        }
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
          actions: detail?.actions,
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
    // localize / showToast are only read inside the failure branch and are re-created on
    // every render (see AGENTS.md), so listing them would re-run this detail fetch — and its
    // redirect — on every render. The effect is keyed on the channel it is resolving.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      const backToSquare = new URLSearchParams(location.search).get("square") === "1";
      navigate(backToSquare ? "/channel?square=1" : "/channel", { replace: true });
    }
  };

  const bumpChannelSquareList = () => setChannelSquareRefreshKey((k) => k + 1);

  // Stable callbacks for the memo'd ChannelSquare — prevents the card list
  // from re-rendering (flashing) when navigate() re-renders Subscription on
  // card click.
  const handleSquareBack = useCallback(() => {
    setShowChannelSquare(false);
    setActiveChannel(null);
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

  // Keep the latest created count available to quota checks.
  const createdChannelCountRef = useRef(0);
  const { isOverQuota } = useEffectiveQuota();

  // Both shells share the same home data and route-driven channel selection.
  const channelPluginEnabled = channelPluginGate === "enabled";
  useChannelStateRefresh(() => {
    void refreshChannelState(queryClient);
  }, channelPluginEnabled);
  useChannelAccessGuard(activeChannel?.id, () => {
    const channelId = activeChannel?.id;
    setActiveChannel(null);
    setFullScreenArticle(null);
    setShowAiAssistant(false);
    if (channelId) navigate(`/channel/share/${encodeURIComponent(channelId)}`, { replace: true });
  });
  const {
    created: { data: createdChannelsForAuto = [], isFetched: createdAutoFetched },
    subscribed: { data: subscribedChannelsForAuto = [], isFetched: subscribedAutoFetched },
    error: channelsError,
    retry: retryChannels,
  } = useChannelLists({ enabled: channelPluginEnabled });

  // True while we still can't tell whether the user has channels: the plugin
  // gate is resolving, or the channel lists haven't finished their first fetch.
  // Wait for both lists before choosing home or discovery.
  const channelsResolving =
    channelPluginGate === "loading" ||
    (channelPluginEnabled && (!createdAutoFetched || !subscribedAutoFetched));

  useEffect(() => {
    createdChannelCountRef.current = createdChannelsForAuto.length;
  }, [createdChannelsForAuto.length]);

  // /channel is the module home on every width, including browser Back from a channel.
  useEffect(() => {
    if (detailChannelId || isShareRoute) return;
    setActiveChannel(null);
  }, [detailChannelId, isShareRoute]);

  const handleChannelSelect = (channel: Channel | null) => {
    if (channel && isDemoId(channel.id)) {
      showToast({ message: localize("com_demo_data.readonly_toast"), severity: NotificationSeverity.INFO });
      return;
    }
    setActiveChannel(channel);
    navigate(channel ? `/channel/${encodeURIComponent(channel.id)}` : "/channel");
  };

  // Create channel - opens drawer (with limit check)
  const handleCreateChannel = () => {
    if (isOverQuota("channel", createdChannelCountRef.current)) {
      showToast({
        message: localize("com_subscription.channel_limit_reached"),
        severity: NotificationSeverity.WARNING,
      });
      return;
    }
    navigate("/channel/create");
  };

  // Channel square
  // Desktop discovers channels in the sidebar's 广场 (~/pages/square). The in-page square
  // remains for mobile and for the deep links that open it (`?square=1`).
  const handleChannelSquare = () => {
    navigate(squareTypePath("channel"));
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

  /** Module home: nothing picked, nothing resolving, and the
   *  user has at least one channel — otherwise the discovery empty state shows instead. */
  const showChannelHome =
    !showChannelSquare &&
    !activeChannel &&
    !channelsResolving &&
    !detailChannelId &&
    createdChannelsForAuto.length + subscribedChannelsForAuto.length > 0;

  return (
    <div className="relative flex min-h-0 flex-1 flex-col touch-desktop:flex-row">
      {/* PC：`?square=1` 深链仍会在本页打开广场（分享链接失效等场景）；广场的常规入口已移到
                侧栏「广场」，这里只留一个返回键作为出口。 */}
      {showChannelSquare ? (
        <div className="absolute right-4 top-[calc(env(safe-area-inset-top,0px)+12px)] z-40">
          <Tooltip content={localize("com_ui_go_back")}>
            <Button
              color="default"
              variant="outlined"
              size="small"
              iconOnly
              aria-label={localize("com_ui_go_back")}
              onClick={handleSquareBack}
            >
              <Outlined.ArrowLeft />
            </Button>
          </Tooltip>
        </div>
      ) : null}
      {showChannelSquare ? (
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <ChannelSquare
            refreshKey={channelSquareRefreshKey}
            onPreviewChannel={handleSquarePreview}
            isH5={isH5}
            onOpenMobileNav={() => setSystemMenuOpen(true)}
          />
        </div>
      ) : (
        <>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            {activeChannel ? (
              <ChannelLayout
                key={`${activeChannel.id}-${channelRefreshToken}`}
                channel={activeChannel}
                onChannelSelect={handleChannelSelect}
                onChannelSettings={(channel) => navigate(`/channel/${channel.id}/settings`)}
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
            ) : channelsError ? (
              <ApiRequestFailure error={channelsError} onRetry={retryChannels} />
            ) : channelsResolving || detailChannelId ? (
              <SubscriptionLoadingView mobile={isH5} onOpenMobileNav={() => setSystemMenuOpen(true)} />
            ) : showChannelHome ? (
              <ChannelHomePage
                createdChannels={createdChannelsForAuto}
                subscribedChannels={subscribedChannelsForAuto}
                onChannelSelect={handleChannelSelect}
                onCreateChannel={handleCreateChannel}
                onOpenMobileNav={() => setSystemMenuOpen(true)}
              />
            ) : (
              <ChannelDiscoveryHome
                enabled
                isH5={isH5}
                previewOpen={previewDrawerOpen}
                onOpenMobileNav={() => setSystemMenuOpen(true)}
                onPreviewChannel={handleSquarePreview}
                onGoSquare={handleChannelSquare}
                onCreateChannel={handleCreateChannel}
              />
            )}
          </div>
        </>
      )}

      {/* Full-screen overlay — absolute inset-0 covers the entire Subscription (including the channel sidebar), but doesn't affect MainLayout's primary navigation */}
      {fullScreenArticle && (
        <SubscriptionArticleOverlay
          article={fullScreenArticle}
          mobile={isH5}
          showAiAssistant={showAiAssistant}
          showFullScreenBtn={showFullScreenBtn}
          enteredViaAiRef={enteredFullscreenViaAiRef}
          onClose={() => setFullScreenArticle(null)}
          onAiAssistantChange={setShowAiAssistant}
          onShowFullScreenBtnChange={setShowFullScreenBtn}
        />
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
