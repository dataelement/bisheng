import { useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from "react";
import { Search, ArrowLeft } from "lucide-react";
import { Input } from "~/components/ui/Input";
import { Button } from "~/components/ui/Button";
import { ChannelSquareCard } from "./ChannelSquareCard";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { getChannelSquareApi, subscribeManagerChannelApi } from "~/api/channels";
import { useLocalize, useScrollbarWhileScrolling } from "~/hooks";

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
}

export default function ChannelSquare({
  onBack,
  title,
  subtitle,
  searchPlaceholder,
  emptyText,
  joinToastPrefix,
  onPreviewChannel,
  fetchApi,
  subscribeApi,
  refreshKey = 0,
}: ChannelSquareProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMorePage, setHasMorePage] = useState(true);
  const [allChannels, setAllChannels] = useState<SquareChannel[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const { onScroll: onScrollShowScrollbar, scrollingProps } = useScrollbarWhileScrolling();
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
      onScrollShowScrollbar();
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
    [hasMorePage, loadingMore, load, onScrollShowScrollbar, page]
  );

  // 将频道分成每行3个
  const channelRows: typeof visibleChannels[] = [];
  for (let i = 0; i < visibleChannels.length; i += 3) {
    channelRows.push(visibleChannels.slice(i, i + 3));
  }

  return (
    <div className="h-full w-full flex flex-col bg-white overflow-hidden">
      {/* 头部区域 */}
      <div
        className="w-full relative overflow-hidden border-b border-[#F0F1F5] bg-center bg-no-repeat bg-cover"
        style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/channel/bgchannel.svg)` }}
      >

        {/* 返回按钮：固定在头部左上，不跟随居中容器偏移 */}
        {onBack && (
          <div className="absolute left-4 top-4 z-10">
            <Button
              variant="ghost"
              onClick={onBack}
              className="h-7 w-7 p-0 rounded-md border border-[#E5E6EB] bg-white text-[#4E5969] hover:bg-[#F7F8FA] hover:text-[#165DFF]"
            >
              <ArrowLeft className="size-3.5" />
            </Button>
          </div>
        )}

        {/* 主要内容 */}
        <div className="relative max-w-[1140px] mx-auto w-full flex flex-col items-center justify-center pt-7 pb-6 px-4">

          <h1 className="text-[26px] font-semibold text-[#335CFF] mb-1">
            {tTitle}
          </h1>
          <p className="text-[13px] text-[#86909C]">
            {tSubtitle}
          </p>
        </div>
      </div>

      {/* 频道列表区域 */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto scroll-on-scroll bg-white"
        onScroll={handleListScroll}
        {...scrollingProps}
      >
        <div className="relative w-full max-w-[480px] mx-auto mb-6">
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
            className="pl-9 h-8 text-[12px] rounded-md bg-white border-[#E5E6EB] focus:border-[#165DFF]"
          />
        </div>
        <div className="max-w-[1032px] mx-auto px-4 pb-4 pt-0">

          {channelRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-[#86909c]">
              <img
                className="size-[120px] mb-3 object-contain opacity-90"
                src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                alt="empty"
              />
              <p className="text-[14px] text-[#86909C]">{tEmptyText}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {channelRows.map((row, rowIndex) => (
                <div key={rowIndex} className="flex gap-3">
                  {row.map((channel) => (
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
                  {/* 补充空白卡片以保持布局 */}
                  {row.length < 3 && (
                    <>
                      {Array.from({ length: 3 - row.length }).map((_, i) => (
                        <div key={`empty-${i}`} className="flex-1 min-w-0" />
                      ))}
                    </>
                  )}
                </div>
              ))}
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
