import { Lock, BookOpen } from "lucide-react";
import { Avatar, AvatarImage } from "~/components/ui/avatar";
import { Button } from "~/components/ui/Button";
import { Card, CardContent } from "~/components/ui/Card";
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";

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
  const localize = useLocalize();
  const getButtonConfig = () => {
    switch (status) {
      case "joined":
        return { text: localize("subscribed") || "已订阅", variant: "secondary" as const, disabled: true };
      case "pending":
        return { text: localize("pending"), variant: "secondary" as const, disabled: true };
      case "private":
        return { text: localize("private"), variant: "secondary" as const, disabled: true };
      default:
        return { text: localize("subscribe") || "订阅", variant: "outline" as const, disabled: false };
    }
  };

  const buttonConfig = getButtonConfig();
  const isPrivate = status === "private";

  return (
    <Card
      className={cn(
        "flex-1 min-w-0 py-2 transition-all cursor-pointer border-[#E5E6EB] hover:border-[#BDD0FF] hover:shadow-sm bg-white",
        isHighlighted && "border-[#7EA6FF] shadow-[0px_4px_12px_0px_rgba(22,93,255,0.12)]"
      )}
    >
      <CardContent className="">
        {/* 标题和按钮 */}
        <div className="flex items-center justify-between mt-1 mb-3">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <h3 className="font-medium text-[15px] text-[#1D2129] truncate">
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
              "h-6 px-2.5 text-[12px] rounded-md flex-shrink-0 ml-2 border",
              buttonConfig.variant === "secondary" &&
              "bg-[#F7F8FA] hover:bg-[#F2F3F5] text-[#86909C] border-[#E5E6EB]",
              buttonConfig.variant === "outline" &&
              "text-[#4E5969] border-[#E5E6EB] hover:text-[#165DFF] hover:border-[#165DFF]"
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
        <p className="text-[12px] text-[#86909C] line-clamp-2 leading-[18px] truncate  mb-3">
          {description}
        </p>

        {/* 创建者和统计信息 */}
        <div className="flex items-center gap-2.5 text-[12px] text-[#86909C]">
          <div className="flex items-center gap-1.5">
            <Avatar className="size-5">
              <AvatarImage src={creatorAvatar || "/default-avatar.png"} alt={creator} />
            </Avatar>
          </div>
          <span>
            {articleCount} {localize("articles")}
          </span>
          <span>{subscriberCount}</span>
        </div>
      </CardContent>
    </Card>
  );
}
