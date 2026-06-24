import { useLocalize } from "~/hooks";
import { Button } from "~/components/ui/Button";
import { SuccessIllustration } from "~/components/illustrations";

interface CreateChannelSuccessContentProps {
    /** 点击「查看频道」 */
    onViewChannel: () => void;
    /** 点击「成员管理」 */
    onManageMembers: () => void;
}

/** 创建成功内容区，可嵌入抽屉内使用 */
export function CreateChannelSuccessContent({
    onViewChannel,
    onManageMembers
}: CreateChannelSuccessContentProps) {
    const localize = useLocalize();
    return (
        <div className="flex min-h-full flex-1 flex-col items-center justify-center py-16">
            <div className="flex flex-col items-center">
                <SuccessIllustration className="h-[120px] w-[120px] mb-4" />
                <div className="mb-8 text-center text-[18px] font-semibold text-[#1D2129]">{localize("com_subscription.channel_create_success")}</div>
                <div className="text-[14px] font-normal leading-6 text-[#999999] text-center mb-10 max-w-[400px] whitespace-pre-line">{localize("com_subscription.system_push_schedule")}</div>
                <div className="flex gap-3">
                    <Button
                        variant="secondary"
                        className="inline-flex h-8 min-w-[100px] items-center justify-center rounded-[6px] border border-blue-500 bg-white px-4 text-[14px] font-normal leading-none text-blue-500 hover:bg-[#E8F3FF]"
                        onClick={onViewChannel}
                    >{localize("com_subscription.view_channel")}</Button>
                    <Button
                        className="inline-flex h-8 min-w-[100px] items-center justify-center rounded-[6px] bg-blue-500 px-4 text-[14px] font-normal leading-none text-white hover:bg-blue-400"
                        onClick={onManageMembers}
                    >{localize("com_subscription.member_management")}</Button>
                </div>
            </div>
        </div>
    );
}
