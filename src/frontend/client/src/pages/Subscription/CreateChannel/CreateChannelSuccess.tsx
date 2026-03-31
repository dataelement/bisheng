import { useLocalize } from "~/hooks";
import { Button } from "~/components/ui/Button";
import { ChannelSuccessIcon } from "~/components/icons/channels";

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
        <div className="flex flex-1 flex-col items-center justify-center py-16">
            <div className="flex flex-col items-center">
                <ChannelSuccessIcon className="w-[120px] h-[120px] mb-5" />
                <div className="text-[20px] font-semibold text-[#1D2129] mb-2">{localize("com_subscription.channel_create_success")}</div>
                <div className="text-[14px] leading-6 text-[#86909C] text-center mb-10 max-w-[400px] whitespace-pre-line">{localize("com_subscription.system_push_schedule")}</div>
                <div className="flex gap-3">
                    <Button
                        variant="secondary"
                        className="min-w-[100px] h-8 rounded-[6px] inline-flex items-center justify-center leading-none bg-white border border-[#165DFF] text-[#165DFF] hover:bg-[#E8F3FF] text-[14px]"
                        onClick={onViewChannel}
                    >{localize("com_subscription.view_channel")}</Button>
                    <Button
                        className="min-w-[100px] h-8 rounded-[6px] inline-flex items-center justify-center leading-none bg-[#165DFF] hover:bg-[#4080FF] text-white text-[14px]"
                        onClick={onManageMembers}
                    >{localize("com_subscription.member_management")}</Button>
                </div>
            </div>
        </div>
    );
}

