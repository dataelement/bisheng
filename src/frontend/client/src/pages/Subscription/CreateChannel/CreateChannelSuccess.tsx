import { Button } from "~/components/ui/Button";

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
    return (
        <div className="flex flex-1 flex-col items-center justify-center py-16">
            <div className="flex flex-col items-center">
                <img
                    src={`${__APP_ENV__.BASE_URL}/assets/channel/success.svg`}
                    alt=""
                    className="w-16 h-16 mb-5"
                />
                <div className="text-[20px] font-semibold text-[#1D2129] mb-2">频道创建成功</div>
                <div className="text-[14px] leading-6 text-[#86909C] text-center mb-10 max-w-[400px]">
                    系统将于每日 00:00 检测信息源更新 次日早上 08:00 进行推送
                </div>
                <div className="flex gap-3">
                    <Button
                        variant="secondary"
                        className="min-w-[100px] h-9 bg-white border border-[#165DFF] text-[#165DFF] hover:bg-[#E8F3FF] text-[14px]"
                        onClick={onViewChannel}
                    >
                        查看频道
                    </Button>
                    <Button
                        className="min-w-[100px] h-9 bg-[#165DFF] hover:bg-[#4080FF] text-white text-[14px]"
                        onClick={onManageMembers}
                    >
                        成员管理
                    </Button>
                </div>
            </div>
        </div>
    );
}

