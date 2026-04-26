import { Lock } from "lucide-react";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { Button } from "~/components/ui/Button";
import { Card, CardContent } from "~/components/ui/Card";
import { cn } from "~/utils";
import { KnowledgeSpace, VisibilityType } from "~/api/knowledge";
import { useLocalize } from "~/hooks";

type SquareSpaceStatus = "join" | "joined" | "pending" | "rejected";

interface KnowledgeSquareCardProps {
    space: KnowledgeSpace;
    status: SquareSpaceStatus;
    onAction?: () => void;
    onPreview?: () => void;
    isHighlighted?: boolean;
    isActing?: boolean;
}

export default function KnowledgeSquareCard({
    space,
    status,
    onAction,
    onPreview,
    isHighlighted = false,
    isActing = false,
}: KnowledgeSquareCardProps) {
    const localize = useLocalize();

    const getButtonConfig = () => {
        switch (status) {
            case "joined":
                return { text: localize("com_knowledge.joined"), variant: "secondary" as const, disabled: true };
            case "pending":
                return { text: localize("com_knowledge.pending"), variant: "secondary" as const, disabled: true };
            case "rejected":
                return { text: localize("com_knowledge.reapply"), variant: "outline" as const, disabled: isActing };
            default: {
                return {
                    // “订阅/申请”动作统一展示为“加入”
                    text: localize("com_knowledge.join"),
                    variant: "outline" as const,
                    disabled: isActing,
                };
            }
        }
    };

    const buttonConfig = getButtonConfig();
    const isPrivateOrLocked = space.visibility !== VisibilityType.PUBLIC;

    const creatorAvatar = space.icon;

    return (
        <Card
            className={cn(
                "group relative flex-1 min-w-0 gap-0 p-0 cursor-pointer rounded-[8px] border-[0.5px] border-solid border-[#EBECF0] bg-[linear-gradient(110deg,#F9FBFE_0%,#FFF_50%,#F9FBFE_100%)] shadow-none transition-all",
                "fine-pointer:hover:bg-[linear-gradient(0deg,#FFF_0%,#FFF_100%),linear-gradient(110deg,#F9FBFE_0%,#FFF_50%,#F9FBFE_100%)] fine-pointer:hover:shadow-[0_8px_20px_0_rgba(117,145,212,0.12)]",
                "after:pointer-events-none after:absolute after:inset-0 after:rounded-[8px] after:border after:border-[#335CFF] after:opacity-0 after:transition-opacity fine-pointer:group-hover:after:opacity-100",
                isHighlighted &&
                "border-[1px] border-solid border-[#335CFF] bg-[linear-gradient(0deg,#FFF_0%,#FFF_100%),linear-gradient(110deg,#F9FBFE_0%,#FFF_50%,#F9FBFE_100%)] shadow-[0_8px_20px_0_rgba(117,145,212,0.12)]"
            )}
            onClick={onPreview}
        >
            <CardContent className="flex flex-col gap-3 p-[12px]">
                <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
                        <h3 className="m-0 min-w-0 shrink truncate text-[14px] font-bold leading-[20px] text-[#1D2129]">
                            {space.name}
                        </h3>
                        {isPrivateOrLocked && (
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
                            "bg-[#F7F8FA] text-[#86909C] border-[#E5E6EB] fine-pointer:hover:bg-[#F2F3F5]",
                            buttonConfig.variant === "outline" &&
                            "text-[#4E5969] border-[#E5E6EB] fine-pointer:hover:text-[#165DFF] fine-pointer:hover:border-[#165DFF]"
                        )}
                        onClick={(e) => {
                            e.stopPropagation();
                            onAction?.();
                        }}
                    >
                        {buttonConfig.text}
                    </Button>
                </div>

                <p
                    className="m-0 line-clamp-2 truncate text-[14px] leading-[20px] text-[#A9AEB8]"
                    title={space.description}
                >
                    {space.description || localize("com_knowledge.no_description")}
                </p>

                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] leading-[18px] text-[#86909C] touch-desktop:flex-nowrap touch-desktop:gap-2.5 touch-desktop:text-[14px] touch-desktop:leading-[20px]">
                    <div className="flex shrink-0 items-center gap-1.5">
                        <Avatar className="border border-white h-5 w-5">
                            {creatorAvatar ? (
                                <AvatarImage src={creatorAvatar} alt={space.creator} />
                            ) : null}
                            <AvatarName name={space.creator} className="text-xs" />
                        </Avatar>
                    </div>

                    <span className="whitespace-nowrap">
                        {space.fileCount}{localize("com_subscription.articles") || localize("com_knowledge.articles_count")}
                    </span>
                    <span className="whitespace-nowrap">
                        {space.memberCount}
                        {localize("com_knowledge.users_count")}
                    </span>
                </div>
            </CardContent>
        </Card>
    );
}
