import { useEffect, useMemo, useRef, useState } from "react";
import { Search, Lightbulb, FileText, TrendingUp, Globe, ArrowLeft } from "lucide-react";
import { Input } from "~/components/ui/Input";
import { Button } from "~/components/ui/Button";
import { ChannelSquareCard } from "./ChannelSquareCard";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { getChannelSquareApi, subscribeManagerChannelApi } from "~/api/channels";
import { useLocalize } from "~/hooks";

type SquareStatus = "join" | "joined" | "pending" | "private";

interface SquareChannel {
  id: string;
  title: string;
  description: string;
  creator: string;
  creatorAvatar?: string;
  articleCount: number;
  subscriberCount: number;
  status: SquareStatus;
  visibility?: "public" | "private" | "approval";
  isHighlighted?: boolean;
}

interface ChannelSquareProps {
  onBack?: () => void;
  title?: string;
  subtitle?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  joinToastPrefix?: string;
}

export default function ChannelSquare({
  onBack,
  title,
  subtitle,
  searchPlaceholder,
  emptyText,
  joinToastPrefix
}: ChannelSquareProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(12);
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMorePage, setHasMorePage] = useState(true);
  const [allChannels, setAllChannels] = useState<SquareChannel[]>([]);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const { showToast } = useToastContext();
  const localize = useLocalize();
  const [joiningId, setJoiningId] = useState<string | null>(null);

  const tTitle = title || localize("explore_channel_plaza");
  const tSubtitle = subtitle || localize("explore_more_channel");
  const tSearchPlaceholder = searchPlaceholder || localize("enter_channel_search");
  const tEmptyText = emptyText || localize("nofound_matching_channel");
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
        await subscribeManagerChannelApi({ channel_id: channelId });
        if (target.visibility === "public") {
          showToast({
            message: localize("subscribe_success") || "订阅成功",
            severity: NotificationSeverity.SUCCESS
          });
        } else {
          showToast({
            message: localize("apply_sent") || "申请已发送",
            severity: NotificationSeverity.SUCCESS
          });
        }
      } catch {
        // 失败时回滚状态
        setAllChannels((prev) =>
          prev.map((c) => (c.id === channelId ? { ...c, status: target.status } : c))
        );
        showToast({
          message: localize("channel_subscribe_failed") || "订阅频道失败，请稍后重试",
          severity: NotificationSeverity.ERROR
        });
      } finally {
        setJoiningId(null);
      }
    })();
  };

  const handleSearch = (e) => {
    const next = e.target.value ?? "";
    if (next.length > 40) {
      showToast({
        message: localize("maximum_character"),
        severity: NotificationSeverity.WARNING
      });
      setSearchQuery(next.slice(0, 40));
      return;
    }
    setSearchQuery(next);
  };

  // 根据搜索词加载频道广场数据
  useEffect(() => {
    const load = async (nextPage: number) => {
      try {
        const res = await getChannelSquareApi({
          keyword: searchQuery.trim() || undefined,
          page: nextPage,
          page_size: 20
        });
        const root: any = res;
        const payload = root.data ?? root;
        const list: any[] = (payload?.data || payload?.list || []) as any[];
        const mapped: SquareChannel[] = list.map((item: any, index: number) => ({
          id: String(item.id ?? item.channel_id ?? index),
          title: String(item.name ?? item.title ?? ""),
          description: String(item.description ?? item.desc ?? "") || "暂无简介",
          creator: String(item.creator ?? item.creator_name ?? ""),
          creatorAvatar: item.creatorAvatar ?? item.creator_avatar,
          articleCount: Number(item.article_count ?? item.articleCount ?? 0),
          subscriberCount: Number(item.subscriber_count ?? item.subscriberCount ?? 0),
          visibility: item.visibility as "public" | "private" | "approval" | undefined,
          status:
            (item.subscription_status === "subscribed"
              ? "joined"
              : (item.status as SquareStatus)) || "join",
          isHighlighted: Boolean(item.isHighlighted ?? item.highlight)
        }));

        setAllChannels(prev =>
          nextPage === 1 ? mapped : [...prev, ...mapped]
        );
        setHasMorePage(mapped.length >= 20);
        setPage(nextPage);
      } catch {
        // 出错时不打断现有列表
      }
    };

    load(1);
  }, [searchQuery]);

  const filteredChannels = searchQuery
    ? allChannels.filter(
      (channel) =>
        channel.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
        channel.description.toLowerCase().includes(searchQuery.toLowerCase())
    )
    : allChannels;

  const visibleChannels = filteredChannels.slice(0, visibleCount);
  const hasMore = visibleCount < filteredChannels.length;

  useEffect(() => {
    setVisibleCount(12);
  }, [searchQuery, allChannels.length]);

  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const onScroll = () => {
      if (loadingMore || !hasMore) return;
      const threshold = 60;
      if (node.scrollTop + node.clientHeight >= node.scrollHeight - threshold) {
        setLoadingMore(true);
        setTimeout(() => {
          setVisibleCount((prev) => Math.min(prev + 9, filteredChannels.length));
          setLoadingMore(false);
        }, 280);
      }
    };
    node.addEventListener("scroll", onScroll);
    return () => node.removeEventListener("scroll", onScroll);
  }, [filteredChannels.length, hasMore, loadingMore]);

  // 将频道分成每行3个
  const channelRows: typeof visibleChannels[] = [];
  for (let i = 0; i < visibleChannels.length; i += 3) {
    channelRows.push(visibleChannels.slice(i, i + 3));
  }

  return (
    <div className="h-full w-full flex flex-col bg-white overflow-hidden">
      {/* 头部区域 */}
      <div className="bg-[#FAFBFF] w-full relative overflow-hidden border-b border-[#F0F1F5]">
        {/* 装饰性图标 */}
        <div className="absolute left-[32%] top-6 opacity-30">
          <Lightbulb className="size-6 text-[#d0ddff]" strokeWidth={1.5} />
        </div>
        <div className="absolute left-[30%] top-14 opacity-30 rotate-[-40deg]">
          <FileText className="size-7 text-[#d0ddff]" strokeWidth={1.5} />
        </div>
        <div className="absolute right-[32%] top-5 opacity-30 rotate-[11deg]">
          <TrendingUp className="size-6 text-[#d0ddff]" strokeWidth={1.5} />
        </div>
        <div className="absolute right-[28%] top-16 opacity-30 rotate-[28deg]">
          <Globe className="size-7 text-[#d0ddff]" strokeWidth={1.5} />
        </div>

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
        <div className="relative max-w-[1140px] mx-auto w-full flex flex-col items-center justify-center pt-7 pb-5 px-4">

          <h1 className="text-[26px] font-semibold text-[#335CFF] mb-1">
            {tTitle}
          </h1>
          <p className="text-[13px] text-[#86909C] mb-3">
            {tSubtitle}
          </p>

          {/* 搜索栏 */}

        </div>
      </div>

      {/* 频道列表区域 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto bg-white">
        <div className="relative w-full max-w-[380px] mx-auto mt-2 mb-1">
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
        <div className="max-w-[1032px] mx-auto px-4 py-4">

          {channelRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-[#86909c]">
              <Search className="size-12 mb-3 opacity-40" />
              <p className="text-[14px] text-[#86909C]">{tEmptyText}</p>
            </div>
          ) : (
            <div className="space-y-3">
              {channelRows.map((row, rowIndex) => (
                <div key={rowIndex} className="flex gap-3">
                  {row.map((channel) => (
                    <ChannelSquareCard
                      key={channel.id}
                      {...channel}
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
                {loadingMore ? "加载中..." : !hasMore ? "没有更多内容了" : ""}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
