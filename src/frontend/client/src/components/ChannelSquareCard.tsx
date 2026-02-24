import { Lock, BookOpen } from "lucide-react";
import { Avatar, AvatarImage } from "~/components/ui/avatar";
import { Button } from "~/components/ui/Button";
import { Card, CardContent } from "~/components/ui/Card";
import { cn } from "~/utils";

interface ChannelSquareCardProps {
  title: string;
  description: string;
  creator: string;
  creatorAvatar?: string;
  articleCount: number;
  subscriberCount: number;
  status: "join" | "joined" | "pending" | "private";
  isHighlighted?: boolean;
  onAction?: () => void;
}

export function ChannelSquareCard({
  title,
  description,
  creator,
  creatorAvatar,
  articleCount,
  subscriberCount,
  status,
  isHighlighted = false,
  onAction
}: ChannelSquareCardProps) {
  const getButtonConfig = () => {
    switch (status) {
      case "joined":
        return { text: "已加入", variant: "secondary" as const, disabled: false };
      case "pending":
        return { text: "申请中", variant: "secondary" as const, disabled: true };
      case "private":
        return { text: "私有", variant: "secondary" as const, disabled: true };
      default:
        return { text: "加入", variant: "outline" as const, disabled: false };
    }
  };

  const buttonConfig = getButtonConfig();
  const isPrivate = status === "private";

  return (
    <Card
      className={cn(
        "flex-1 min-w-0 transition-all hover:shadow-lg cursor-pointer",
        isHighlighted && "border-[#335cff] shadow-[0px_8px_20px_0px_rgba(117,145,212,0.12)]"
      )}
    >
      <CardContent className="p-4">
        {/* 标题和按钮 */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <div className="flex-shrink-0 bg-[#f0f5ff] p-1.5 rounded">
              <BookOpen className="size-4 text-[#335cff]" />
            </div>
            <h3 className="font-medium text-base text-[#212121] truncate">
              {title}
            </h3>
            {isPrivate && (
              <Lock className="size-3.5 text-[#818181] flex-shrink-0" />
            )}
          </div>
          <Button
            variant={buttonConfig.variant}
            size="sm"
            disabled={buttonConfig.disabled}
            className={cn(
              "h-7 px-3 text-sm rounded-md flex-shrink-0 ml-2",
              buttonConfig.variant === "secondary" &&
                "bg-[#f8f8f8] hover:bg-[#f0f0f0] text-[#212121] border-[#ececec]"
            )}
            onClick={(e) => {
              e.stopPropagation();
              onAction?.();
            }}
          >
            {buttonConfig.text}
          </Button>
        </div>

        {/* 描述 */}
        <p className="text-sm text-[#a9aeb8] mb-3 line-clamp-2 leading-relaxed min-h-[40px]">
          {description}
        </p>

        {/* 创建者和统计信息 */}
        <div className="flex items-center gap-3 text-sm text-[#818181]">
          <div className="flex items-center gap-1.5">
            <Avatar className="size-5">
              <AvatarImage src={creatorAvatar || "/default-avatar.png"} alt={creator} />
            </Avatar>
            <span>{creator}</span>
          </div>
          <span>{articleCount} 篇内容</span>
          <span>{subscriberCount} 订阅</span>
        </div>
      </CardContent>
    </Card>
  );
}
