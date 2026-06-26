import { memo, useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from "react";
import { Search } from "lucide-react";
import { EmptyStateIllustration } from "~/components/illustrations";
import { Outlined } from "bisheng-icons";
import { Input } from "~/components/ui/Input";
import { ChannelSquareCard } from "./ChannelSquareCard";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { getChannelSquareApi, subscribeManagerChannelApi } from "~/api/channels";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { useLocalize, useScrollRevealRef } from "~/hooks";
import { cn } from "~/utils";

type SquareStatus = "join" | "joined" | "pending" | "private" | "rejected";

interface SquareChannel {
  id: string;
  title: string;
  description: string;
  creator: string;
  creatorAvatars?: string[]; // 最多 3 个信息源头像
  articleCount: number;
  subscriberCount: number;
  status: SquareStatus;
  visibility?: "public" | "private" | "review";
  isHighlighted?: boolean;
}

interface ChannelSquareProps {
  onBack?: () => void;
  title?: string;
  subtitle?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  joinToastPrefix?: string;
  onPreviewChannel?: (id: string) => void;
  /** Override the list-fetch API (default: getChannelSquareApi) */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  fetchApi?: (params: { keyword?: string; page: number; page_size: number }) => Promise<any>;
  /** Override the subscribe API (default: subscribeManagerChannelApi) */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  subscribeApi?: (id: string) => Promise<any>;
  /** Bump to force a full reload of the square list (e.g. after subscribe in preview drawer). */
  refreshKey?: number;
  /** H5: render the top bar (hamburger). The 频道/广场 toggle is a persistent
   *  single instance rendered above both views (Subscription/index), not here. */
  isH5?: boolean;
  /** H5: open the mobile system menu (hamburger). */
  onOpenMobileNav?: () => void;
}

function ChannelSquare({
  title,
  subtitle,
  searchPlaceholder,
  emptyText,
  joinToastPrefix,
  onPreviewChannel,
  fetchApi,
  subscribeApi,
  refreshKey = 0,
  isH5 = false,
  onOpenMobileNav,
}: ChannelSquareProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMorePage, setHasMorePage] = useState(true);
  const [allChannels, setAllChannels] = useState<SquareChannel[]>([]);
  // Track only the very first page-1 fetch so the empty state never flashes
  // before data arrives. Subsequent search/refresh reloads keep the existing
  // list (search filters client-side), so we don't re-enter the loading view.
  const [initialLoading, setInitialLoading] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const scrollRevealRef = useScrollRevealRef<HTMLDivElement>();
  const { showToast } = useToastContext();
  const localize = useLocalize();
  const [joiningId, setJoiningId] = useState<string | null>(null);

  const tTitle = title || localize("com_subscription.explore_channel_plaza");
  const tSubtitle = subtitle || localize("com_subscription.explore_more_channel");
  const tSearchPlaceholder = searchPlaceholder || localize("com_subscription.enter_channel_search");
  const tEmptyText = emptyText || "无相关内容，请重新搜索";
  const tJoinPrefix = joinToastPrefix || localize("applied_join_channel");

  const handleJoinChannel = (channelId: string, channelTitle: string) => {
    const target = allChannels.find((c) => c.id === channelId);
    if (!target || target.status !== "join" || joiningId) return;

    (async () => {
      try {
        setJoiningId(channelId);
        const nextStatus: SquareStatus =
          target.visibility === "public" ? "joined" : "pending";

        // 先乐观更新为目标状态
        setAllChannels((prev) =>
          prev.map((c) => (c.id === channelId ? { ...c, status: nextStatus } : c))
        );

        const res: any = subscribeApi
          ? await subscribeApi(channelId)
          : await subscribeManagerChannelApi({ channel_id: channelId });
        const root = res;
        const statusCode = root?.status_code ?? root?.code;
        if (statusCode && statusCode !== 200) {
          const msg =
            root?.status_message ||
            root?.message ||
            localize("channel_subscribe_failed") ||
            "订阅频道失败，请稍后重试";
          throw new Error(msg);
        }
        if (target.visibility === "public") {
          showToast({
            message: localize("subscribe_success") || "订阅成功",
            severity: NotificationSeverity.SUCCESS
          });
        } else {
          showToast({
            message: localize("com_subscription.apply_sent") || "申请已发送",
            severity: NotificationSeverity.SUCCESS
          });
        }
        // 与服务端对齐订阅态（含需审核频道的 pending），避免仅乐观更新与接口不一致
        load(1);
      } catch (e: any) {
        // 失败时回滚状态
        setAllChannels((prev) =>
          prev.map((c) => (c.id === channelId ? { ...c, status: target.status } : c))
        );
        // use interceptors toast
        // showToast({
        //   message:
        //     e?.message ||
        //     localize("channel_subscribe_failed") ||
        //     "订阅频道失败，请稍后重试",
        //   severity: NotificationSeverity.ERROR
        // });
      } finally {
        setJoiningId(null);
      }
    })();
  };

  const handleSearch = (e) => {
    const next = e.target.value ?? "";
    if (next.length > 40) {
      showToast({
        message: localize("com_subscription.maximum_character"),
        severity: NotificationSeverity.WARNING
      });
      setSearchQuery(next.slice(0, 40));
      return;
    }
    setSearchQuery(next);
  };

  const load = useCallback(
    async (nextPage: number) => {
      try {
        const res = fetchApi
          ? await fetchApi({ keyword: searchQuery.trim() || undefined, page: nextPage, page_size: 20 })
          : await getChannelSquareApi({
            keyword: searchQuery.trim() || undefined,
            page: nextPage,
            page_size: 20
          });
        const root: any = res;
        const payload = root.data ?? root;
        const list: any[] = (payload?.data || payload?.list || []) as any[];
        const mapped: SquareChannel[] = list
          .map((item: any) => {
            const rawId = item.id ?? item.channel_id;
            if (!rawId) return null;
            const sourceInfos: any[] = Array.isArray(item.source_infos) ? item.source_infos : [];
            const avatars = sourceInfos
              .map((s) => s.source_icon)
              .filter(Boolean)
              .slice(0, 3);

            return {
              id: String(rawId),
              title: String(item.name ?? item.title ?? ""),
              description: String(item.description ?? item.desc ?? "") || "暂无简介",
              creator: String(item.creator ?? item.creator_name ?? ""),
              creatorAvatars: avatars,
              articleCount: Number(item.article_count ?? item.articleCount ?? 0),
              subscriberCount: Number(item.subscriber_count ?? item.subscriberCount ?? 0),
              visibility: item.visibility as "public" | "private" | "review" | undefined,
              status: (() => {
                const subStatus = String(item.subscription_status ?? "");
                // 后端约定：not_subscribed=订阅，subscribed=已订阅，pending=申请中，rejected=已驳回
                if (subStatus === "subscribed") return "joined";
                if (subStatus === "pending") return "pending";
                if (subStatus === "rejected") return "rejected";
                if (subStatus === "not_subscribed") return "join";
                return (item.status as SquareStatus) || "join";
              })(),
              isHighlighted: Boolean(item.isHighlighted ?? item.highlight)
            } as SquareChannel;
          })
          .filter((c): c is SquareChannel => c !== null);

        setAllChannels(prev =>
          nextPage === 1 ? mapped : [...prev, ...mapped]
        );
        setHasMorePage(mapped.length >= 20);
        setPage(nextPage);
      } catch {
        // 出错时不打断现有列表
      } finally {
        if (nextPage === 1) setInitialLoading(false);
      }
    },
    [searchQuery]
  );

  // 根据搜索词 / 外部刷新信号加载频道广场数据
  useEffect(() => {
    load(1);
  }, [searchQuery, load, refreshKey]);

  const filteredChannels = searchQuery
    ? allChannels.filter(
      (channel) =>
        channel.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        channel.description.toLowerCase().includes(searchQuery.toLowerCase())
    )
    : allChannels;

  const visibleChannels = filteredChannels;

  const handleListScroll = useCallback(
    (e: UIEvent<HTMLDivElement>) => {
      const node = e.currentTarget;
      if (loadingMore || !hasMorePage) return;
      const threshold = 60;
      if (node.scrollTop + node.clientHeight >= node.scrollHeight - threshold) {
        setLoadingMore(true);
        load(page + 1).finally(() => {
          setLoadingMore(false);
        });
      }
    },
    [hasMorePage, loadingMore, load, page]
  );

  return (
    <div className="h-full w-full flex flex-col bg-white overflow-hidden">
      {/* H5 顶部栏：侧栏按钮。频道/广场 切换器为跨视图常驻单实例（见 Subscription/index）。 */}
      {isH5 ? (
        <div className="shrink-0 bg-white pt-[calc(env(safe-area-inset-top,0px)+8px)]">
          <div className="relative flex h-11 items-center px-4">
            {onOpenMobileNav ? (
              <button
                type="button"
                aria-label={localize("com_nav_open_sidebar")}
                onClick={onOpenMobileNav}
                className="inline-flex size-5 shrink-0 items-center justify-center text-[#212121]"
              >
                <Outlined.SidebarMenu className="size-5" />
              </button>
            ) : (
              <div className="size-5 shrink-0" aria-hidden />
            )}
            {/* 频道/广场 切换器为跨视图常驻单实例（见 Subscription/index），
                屏幕居中悬浮在此行之上，这里不再各自渲染。 */}
          </div>
        </div>
      ) : null}
      {/* 头部区域 */}
      <div
        className="w-full relative overflow-hidden border-b border-[#F0F1F5] bg-blue-500/[0.05]"
      >
        {/* Decorative scattered icons — kept from the original banner art, recolored
            via a brand-tinted mask layer so they follow the blue ⇄ green theme. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 bg-blue-200"
          style={{
            WebkitMaskImage: `url(${__APP_ENV__.BASE_URL}/assets/channel/bgchannel-icons.svg)`,
            maskImage: `url(${__APP_ENV__.BASE_URL}/assets/channel/bgchannel-icons.svg)`,
            WebkitMaskSize: "cover",
            maskSize: "cover",
            WebkitMaskPosition: "center",
            maskPosition: "center",
            WebkitMaskRepeat: "no-repeat",
            maskRepeat: "no-repeat",
          }}
        />

        {/* 主要内容 */}
        <div className="relative mx-auto flex w-full max-w-[1140px] flex-col items-center justify-center px-4 pb-6 pt-7">

          <h1 className="mb-1 text-[26px] font-semibold text-blue-500">
            {tTitle}
          </h1>
          <p className="text-[13px] text-[#86909C]">
            {tSubtitle}
          </p>
        </div>
      </div>

      {/* 频道列表区域 */}
      <div
        ref={(el) => {
          scrollRef.current = el;
          scrollRevealRef(el);
        }}
        className="flex-1 flex flex-col overflow-y-auto scrollbar-on-scroll bg-white"
        onScroll={handleListScroll}
      >
        <div className={cn("mx-auto mb-6 mt-6 w-full max-w-[480px]", isH5 && "px-4")}>
          <div className="relative w-full">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#8B8FA8] pointer-events-none" />
            <Input
              type="text"
              placeholder={tSearchPlaceholder}
              value={searchQuery}
              onChange={handleSearch}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  // 回车触发，当前为实时搜索，保留该交互语义
                }
              }}
              className="pl-9 h-8 text-[12px] rounded-md bg-white border-[#E5E6EB] focus:border-[#DDDDDD] focus:ring-2 focus:ring-[#F1F5F9]"
            />
          </div>
        </div>
        <div className="flex-1 flex flex-col w-full max-w-[1032px] mx-auto px-4 pb-4 pt-0">

          {initialLoading ? (
            <div className="flex-1 flex flex-col items-center justify-center text-[#86909c]">
              <LoadingIcon className="size-20 text-primary" />
            </div>
          ) : visibleChannels.length === 0 ? (
            <div className="flex-1 flex flex-col items-center justify-center text-[#86909c]">
              <EmptyStateIllustration className="size-[120px] mb-4 opacity-90" />
              <p className="text-[14px] font-normal text-[#999999]">{tEmptyText}</p>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3 min-[768px]:grid-cols-3">
                {visibleChannels.map((channel) => (
                    <ChannelSquareCard
                      key={channel.id}
                      title={channel.title}
                      description={channel.description}
                      creator={channel.creator}
                      creatorAvatars={channel.creatorAvatars}
                      articleCount={channel.articleCount}
                      subscriberCount={channel.subscriberCount}
                      status={channel.status}
                      visibility={channel.visibility}
                      isHighlighted={channel.isHighlighted}
                      onPreview={() => onPreviewChannel?.(channel.id)}
                      onAction={() => handleJoinChannel(channel.id, channel.title)}
                    />
                ))}
              </div>
              <div className="h-10 flex items-center justify-center text-[12px] text-[#C9CDD4]">
                {loadingMore
                  ? "加载中..."
                  : !hasMorePage
                    ? "没有更多内容了"
                    : ""}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// memo: skip re-render when parent (Subscription) re-renders due to navigate/
// location changes. Combined with useCallback'd onPreviewChannel/onBack in the
// parent, this stops the card list from repainting (flashing) on card click.
export default memo(ChannelSquare);
