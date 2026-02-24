import { useState } from "react";
import { Search, ArrowLeft, Lightbulb, FileText, TrendingUp, Globe } from "lucide-react";
import { Input } from "~/components/ui/Input";
import { Button } from "~/components/ui/Button";
import { ChannelSquareCard } from "~/components/ChannelSquareCard";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";

// 模拟频道数据
const mockChannels = [
  {
    id: "1",
    title: "国家粮食安全政策",
    description: "汇总国家层面粮食安全、储备调控、农业补贴与进出口管理政策，提供权威政策文本与解读。",
    creator: "庄婧瑶",
    creatorAvatar: "/avatars/user1.png",
    articleCount: 504,
    subscriberCount: 27,
    status: "join" as const,
    isHighlighted: true
  },
  {
    id: "2",
    title: "全球粮食市场监测库",
    description: "跟踪主要粮食出口国供需变化、国际粮价走势与贸易政策，支持全球市场分析。",
    creator: "庄婧瑶",
    creatorAvatar: "/avatars/user2.png",
    articleCount: 504,
    subscriberCount: 27,
    status: "joined" as const
  },
  {
    id: "3",
    title: "玉米产业链",
    description: "覆盖玉米种植、收储、加工、贸易及终端应用的全产业链资料与研究报告。",
    creator: "庄婧瑶",
    creatorAvatar: "/avatars/user3.png",
    articleCount: 504,
    subscriberCount: 27,
    status: "join" as const
  },
  {
    id: "4",
    title: "小麦与面粉行业资料库",
    description: "收录小麦产区数据、质量标准、加工技术及行业政策与趋势分析。",
    creator: "庄婧瑶",
    creatorAvatar: "/avatars/user4.png",
    articleCount: 504,
    subscriberCount: 27,
    status: "pending" as const
  },
  {
    id: "5",
    title: "大豆与油脂政策研究",
    description: "聚焦大豆进口、国储拍卖、豆粕等副产品及油脂政策与贸易动态。",
    creator: "庄婧瑶",
    creatorAvatar: "/avatars/user5.png",
    articleCount: 504,
    subscriberCount: 27,
    status: "join" as const
  },
  {
    id: "6",
    title: "农业可持续政策研究",
    description: "探讨促进农产品供应链低碳化、循环经济等政策导向的知识库。",
    creator: "庄婧瑶",
    creatorAvatar: "/avatars/user1.png",
    articleCount: 504,
    subscriberCount: 27,
    status: "join" as const
  },
  {
    id: "7",
    title: "粮食物流与储备管理",
    description: "涵盖粮食仓储设施、运输网络、损耗管理与智能仓储技术相关内容。",
    creator: "庄婧瑶",
    creatorAvatar: "/avatars/user2.png",
    articleCount: 504,
    subscriberCount: 27,
    status: "join" as const
  },
  {
    id: "8",
    title: "农业补贴与扶持政策",
    description: "汇总各地区生产补贴、科技补贴、金融扶持等政策文件与实操指南。",
    creator: "庄婧瑶",
    creatorAvatar: "/avatars/user3.png",
    articleCount: 504,
    subscriberCount: 27,
    status: "join" as const
  },
  {
    id: "9",
    title: "粮食贸易与关税政策",
    description: "追踪进出口配额、关税调整、贸易协定及国际粮食组织政策与报告数据。",
    creator: "庄婧瑶",
    creatorAvatar: "/avatars/user4.png",
    articleCount: 504,
    subscriberCount: 27,
    status: "private" as const
  }
];

interface ChannelSquareProps {
  onBack?: () => void;
}

export default function ChannelSquare({ onBack }: ChannelSquareProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const { showToast } = useToastContext();

  const handleJoinChannel = (channelId: string, channelTitle: string) => {
    showToast({
      message: `已申请加入频道：${channelTitle}`,
      severity: NotificationSeverity.SUCCESS
    });
  };

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value);
  };

  const filteredChannels = searchQuery
    ? mockChannels.filter(
        (channel) =>
          channel.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
          channel.description.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : mockChannels;

  // 将频道分成每行3个
  const channelRows = [];
  for (let i = 0; i < filteredChannels.length; i += 3) {
    channelRows.push(filteredChannels.slice(i, i + 3));
  }

  return (
    <div className="h-screen flex flex-col bg-white overflow-hidden">
      {/* 头部区域 */}
      <div className="bg-[#fafcff] w-full relative overflow-hidden border-b border-[#ececec]">
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

        {/* 主要内容 */}
        <div className="relative flex flex-col items-center justify-center py-8 px-4">
          {/* 返回按钮 */}
          {onBack && (
            <div className="absolute left-6 top-8">
              <Button
                variant="ghost"
                size="sm"
                onClick={onBack}
                className="text-[#666] hover:text-[#335cff]"
              >
                <ArrowLeft className="size-4 mr-1" />
                返回
              </Button>
            </div>
          )}

          <h1 className="text-2xl font-semibold text-[#335cff] mb-1">
            探索频道广场
          </h1>
          <p className="text-sm text-[#666] mb-6">
            您可以探索更多的频道并加入订阅
          </p>

          {/* 搜索栏 */}
          <div className="relative w-full max-w-[480px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#8B8FA8] pointer-events-none" />
            <Input
              type="text"
              placeholder="输入频道名称或简介进行搜索"
              value={searchQuery}
              onChange={handleSearch}
              className="pl-9 h-9 text-sm rounded-md bg-white"
            />
          </div>
        </div>
      </div>

      {/* 频道列表区域 */}
      <div className="flex-1 overflow-y-auto bg-white">
        <div className="max-w-[1200px] mx-auto px-6 py-6">
          {channelRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-64 text-[#86909c]">
              <Search className="size-12 mb-4 opacity-50" />
              <p>未找到匹配的频道</p>
            </div>
          ) : (
            <div className="space-y-4">
              {channelRows.map((row, rowIndex) => (
                <div key={rowIndex} className="flex gap-4">
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
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
