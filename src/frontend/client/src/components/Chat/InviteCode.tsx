import type React from "react"
    ; ('"use client')

import { useState } from "react"
import { Button, Input } from "../ui";
import { Card, CardContent } from "../ui/Card";
import { bindInviteCode } from "~/api/linsight";
import { useGetUserLinsightCountQuery } from "~/data-provider";
import { useToastContext } from "~/Providers";

export default function InvitationCodeForm({ setShowCode }) {
    const [invitationCode, setInvitationCode] = useState("")
    const [error, setError] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const { refetch } = useGetUserLinsightCountQuery()
    const { showToast } = useToastContext();

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
        <div className={`min-h-screen flex items-center justify-center p-4 relative z-10`}>
            <Card className="w-full max-w-screen-md">
                <CardContent className="p-8">
                    {/* BISHENG Logo */}
                    <div className="text-center mb-8">
                        <div className="text-6xl font-bold text-blue-200 mb-4 tracking-wider">LINSIGHT</div>
                    </div>

                    {/* Form */}
                    <form onSubmit={handleSubmit} className="space-y-6">
                        {/* Title */}
                        <div className="text-center">
                            <h2 className="text-xl font-medium text-gray-900 mb-6">Invitation Code</h2>
                        </div>

                        {/* Input Field */}
                        <div className="space-y-2">
                            <Input
                                type="text"
                                value={invitationCode}
                                onChange={(e) => setInvitationCode(e.target.value)}
                                placeholder=""
                                className="w-full h-12 rounded-2xl border-primary focus:border-blue-500 px-4"
                                disabled={isLoading}
                            />

                            {/* Error Message */}
                            <p className="text-red-500 text-sm mt-2 px-4 h-6">{error}</p>
                        </div>

                        {/* Description */}
                        <div className="text-center">
                            <p className="text-gray-600 text-sm">输入BISHENG提供的邀请码，以获得相应的灵思使用次数～</p>
                        </div>

                        {/* Submit Button */}
                        <div className="text-center pt-4">
                            <Button
                                type="submit"
                                disabled={isLoading || !invitationCode.trim()}
                                className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-2 rounded-lg font-medium disabled:opacity-50"
                            >
                                {isLoading ? "提交中..." : "提交"}
                            </Button>
                        </div>
                    </form>
                </CardContent>
            </Card>
        </div>
    )
}
