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
                <ChannelSuccessIcon className="h-[120px] w-[120px] mb-5" />
                <div className="mb-2 text-center text-[20px] font-normal text-[#1D2129]">{localize("com_subscription.channel_create_success")}</div>
                <div className="text-[14px] leading-6 text-[#86909C] text-center mb-10 max-w-[400px] whitespace-pre-line">{localize("com_subscription.system_push_schedule")}</div>
                <div className="flex gap-3">
                    <Button
                        variant="secondary"
                        className="inline-flex h-8 min-w-[100px] items-center justify-center rounded-[6px] border border-[#165DFF] bg-white px-4 text-[14px] font-normal leading-none text-[#165DFF] hover:bg-[#E8F3FF]"
                        onClick={onViewChannel}
                    >{localize("com_subscription.view_channel")}</Button>
                    <Button
                        className="inline-flex h-8 min-w-[100px] items-center justify-center rounded-[6px] bg-[#165DFF] px-4 text-[14px] font-normal leading-none text-white hover:bg-[#4080FF]"
                        onClick={onManageMembers}
                    >{localize("com_subscription.member_management")}</Button>
                </div>
            </div>
        </div>
    );
}
