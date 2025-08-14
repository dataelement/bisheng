import { useState } from "react";
import { bindInviteCode } from "~/api/linsight";
import { useGetBsConfig, useGetUserLinsightCountQuery } from "~/data-provider";
import { useToastContext } from "~/Providers";
import { Button, Dialog, DialogContent, Input } from "../ui";

export default function InvitationCodeForm({ showCode, setShowCode }) {
    const [invitationCode, setInvitationCode] = useState("")
    const [error, setError] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const { refetch } = useGetUserLinsightCountQuery()
    const { showToast } = useToastContext();
    const { data: bsConfig } = useGetBsConfig()

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()

        if (!invitationCode.trim()) {
            setError("请输入邀请码")
            return
        }

        setIsLoading(true)
        setError("")

        try {
            const result = await bindInviteCode(invitationCode.trim())
            console.log('result :>> ', result);
            if (result.status_code === 500) {
                setError(result.status_message || "提交失败")
                // setError("您输入的邀请码无效")
                // setError("已绑定其他邀请码")
            } else {
                refetch()
                // 成功处理
                setInvitationCode("")
                setError("")
                setShowCode(false)
                showToast({ message: result.status_message, status: 'success' });
            }

        } catch (err) {
            setError("网络错误，请稍后重试")
        } finally {
            setIsLoading(false)
        }
    }

    return (
        <Dialog open={showCode} onOpenChange={setShowCode}>
            <DialogContent className="sm:max-w-[560px]">
                <div className="p-2">
                    {/* BISHENG Logo */}
                    <div className="" style={{ backgroundImage: `url('${__APP_ENV__.BASE_URL}/assets/diandian.png')` }}>
                        <div className="text-2xl font-bold text-primary pt-20 pl-8">Linsight 邀请码</div>
                        {/* Description */}
                        <p className="text-sm mt-3 pl-8">输入 BISHENG 提供的邀请码，开启你的灵思之旅。</p>
                    </div>

                    {/* Form */}
                    <form onSubmit={handleSubmit} className="mt-10 px-8">
                        {/* Input Field */}
                        <div className="flex gap-3">
                            <Input
                                type="text"
                                value={invitationCode}
                                onChange={(e) => setInvitationCode(e.target.value)}
                                placeholder="请输入"
                                maxLength={50}
                                className=""
                                disabled={isLoading}
                            />
                            {/* Submit Button */}
                            <Button
                                type="submit"
                                disabled={isLoading || !invitationCode.trim()}
                                className="px-8 h-10"
                            >
                                {isLoading ? "提交中..." : "提交"}
                            </Button>
                        </div>
                        {/* Error Message */}
                        <p className="text-red-500 text-sm mt-3 px-2 h-6">{error}</p>
                        {bsConfig?.waiting_list_url && <p className="text-xs mt-3 px-2 h-6">没有邀请码？<a className="text-primary" href={bsConfig.waiting_list_url} target="_blank" rel="noreferrer">点击这里申请体验资格</a></p>}
                    </form>
                </div>
            </DialogContent>
        </Dialog >
    )
}
