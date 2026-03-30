import { Lock } from "lucide-react";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/avatar";
import { Button } from "~/components/ui/Button";
import { Card, CardContent } from "~/components/ui/Card";
import { cn } from "~/utils";
import { KnowledgeSpace, VisibilityType } from "~/api/knowledge";
import { useLocalize } from "~/hooks";

type SquareSpaceStatus = "join" | "joined" | "pending";

interface KnowledgeSquareCardProps {
    space: KnowledgeSpace;
    status: SquareSpaceStatus;
    onAction?: () => void;
    onPreview?: () => void;
    isHighlighted?: boolean;
}

export default function KnowledgeSquareCard({
    space,
    status,
    onAction,
    onPreview,
    isHighlighted = false,
}: KnowledgeSquareCardProps) {
    const localize = useLocalize();

    const getButtonConfig = () => {
        switch (status) {
            case "joined":
                return { text: localize("subscribed") || localize("com_knowledge.joined"), variant: "secondary" as const, disabled: true };
            case "pending":
                return { text: localize("pending") || localize("com_knowledge.applying"), variant: "secondary" as const, disabled: true };
            default: {
                return {
                    // “订阅/申请”动作统一展示为“加入”
                    text: localize("com_knowledge.join"),
                    variant: "outline" as const,
                    disabled: false,
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
                "flex-1 min-w-0 py-2 transition-all cursor-pointer border-[#E5E6EB] hover:border-[#BDD0FF] hover:shadow-sm bg-white",
                isHighlighted && "border-[#7EA6FF] shadow-[0px_4px_12px_0px_rgba(22,93,255,0.12)]"
            )}
            onClick={onPreview}
        >
            <CardContent>
                <div className="flex items-center justify-between mt-1 mb-3">
                    <div className="flex items-center gap-2 flex-1 min-w-0">
                        <h3 className="font-bold text-[15px] text-[#1D2129] truncate">{space.name}</h3>
                        {isPrivateOrLocked && <Lock className="size-3.5 text-[#818181] flex-shrink-0" />}
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

                <p
                    className="text-[12px] text-[#86909C] line-clamp-2 leading-[18px] truncate mb-3"
                    title={space.description}
                >
                    {space.description || localize("com_knowledge.no_description")}
                </p>

                <div className="flex items-center gap-2.5 text-[12px] text-[#86909C]">
                    <div className="flex items-center gap-1.5">
                        <Avatar className="border border-white h-6 w-6">
                            {creatorAvatar ? (
                                <AvatarImage src={creatorAvatar} alt={space.creator} />
                            ) : null}
                            <AvatarName name={space.creator} className="text-xs" />
                        </Avatar>
                    </div>

                    <span>
                        {space.fileCount} {localize("com_subscription.articles") || localize("com_knowledge.articles_count")}
                    </span>
                    <span>
                        {space.memberCount}
                        {localize("com_knowledge.users_count")}
                    </span>
                </div>
            </CardContent>
        </Card>
    );
}

