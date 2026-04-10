import { Lock } from "lucide-react";
import { Avatar, AvatarImage } from "~/components/ui/Avatar";
import { Button } from "~/components/ui/Button";
import { Card, CardContent } from "~/components/ui/Card";
import { cn } from "~/utils";
import { useLocalize } from "~/hooks";

interface ChannelSquareCardProps {
  title: string;
  description: string;
  creator: string;
  creatorAvatars?: string[];
  articleCount: number;
  subscriberCount: number;
  status: "join" | "joined" | "pending" | "private" | "rejected";
  visibility?: "public" | "private" | "review";
  isHighlighted?: boolean;
  onAction?: () => void;
  onPreview?: () => void;
}

export function ChannelSquareCard({
  title,
  description,
  creator,
  creatorAvatars,
  articleCount,
  subscriberCount,
  status,
  visibility,
  isHighlighted = false,
  onAction,
  onPreview
}: ChannelSquareCardProps) {
  const localize = useLocalize();

  const getButtonConfig = () => {
    switch (status) {
      case "joined":
        return { text: localize("com_subscription.subscribed"), variant: "secondary" as const, disabled: true };
      case "pending":
        return { text: localize("pending"), variant: "secondary" as const, disabled: true };
      case "private":
        return { text: localize("private"), variant: "secondary" as const, disabled: true };
      case "rejected":
        return { text: localize("rejected") || "已驳回", variant: "secondary" as const, disabled: true };
      default:
        return { text: localize("subscribe") || "订阅", variant: "outline" as const, disabled: false };
    }
  };

  const buttonConfig = getButtonConfig();
  const isPrivateOrReview =
    visibility === "private" || visibility === "review" || status === "private";

  return (
    <Card
      className={cn(
        "flex-1 min-w-0 gap-0 p-0 cursor-pointer rounded-[8px] border-[0.5px] border-solid border-[#EBECF0] bg-[linear-gradient(110deg,#F9FBFE_0%,#FFF_50%,#F9FBFE_100%)] shadow-none transition-all",
        "hover:border-[1px] hover:border-solid hover:border-[#335CFF] hover:bg-[linear-gradient(0deg,#FFF_0%,#FFF_100%),linear-gradient(110deg,#F9FBFE_0%,#FFF_50%,#F9FBFE_100%)] hover:shadow-[0_8px_20px_0_rgba(117,145,212,0.12)]",
        isHighlighted &&
          "border-[1px] border-solid border-[#335CFF] bg-[linear-gradient(0deg,#FFF_0%,#FFF_100%),linear-gradient(110deg,#F9FBFE_0%,#FFF_50%,#F9FBFE_100%)] shadow-[0_8px_20px_0_rgba(117,145,212,0.12)]"
      )}
      onClick={onPreview}
    >
      <CardContent className="flex flex-col gap-3 p-[12px]">
        {/* 标题和按钮 */}
        <div className="flex items-center justify-between gap-2">
          {/* 标题不要 flex-1：短标题时宽度跟内容走，锁才能紧贴文字；长标题靠 shrink+truncate */}
          <div className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
            <h3 className="m-0 min-w-0 shrink truncate text-[14px] font-bold leading-[20px] text-[#1D2129]">
              {title}
            </h3>
            {isPrivateOrReview && (
              <Lock className="size-3.5 shrink-0 text-[#818181]" aria-hidden />
            )}
          </div>
          <Button
            variant={buttonConfig.variant}
            size="sm"
            disabled={buttonConfig.disabled}
            className={cn(
              "h-[28px] min-h-[28px] px-2.5 text-[12px] font-normal rounded-md flex-shrink-0 ml-2 border",
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

        {/* 描述：两行截断，hover 显示完整 tooltip */}
        <p
          className="m-0 line-clamp-2 truncate text-[14px] leading-[20px] text-[#A9AEB8]"
          title={description}
        >
          {description}
        </p>

        {/* 创建者和统计信息 */}
        <div className="flex items-center gap-2.5 text-[14px] leading-[20px] text-[#86909C]">
          <div className="flex items-center gap-1.5">
            {creatorAvatars && creatorAvatars.length > 0 ? (
              <div className="flex -space-x-1.5">
                {creatorAvatars.slice(0, 3).map((src, idx) => (
                  <Avatar
                    key={idx}
                    className="h-[20px] w-[20px] border border-white"
                  >
                    <AvatarImage src={src} alt={creator} className="object-cover" />
                  </Avatar>
                ))}
              </div>
            ) : (
              <Avatar className="h-[20px] w-[20px] border border-white">
                <AvatarImage src="/default-avatar.png" alt={creator} className="object-cover" />
              </Avatar>
            )}
          </div>
          <span>
            {articleCount} {localize("com_subscription.articles")}
          </span>
          <span>{subscriberCount}{localize("com_ui_subscription")}</span>
        </div>
      </CardContent>
    </Card>
  );
}
