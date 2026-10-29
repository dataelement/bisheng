/** 失败原因展示，与门户异常文件列表同一套备注解析。 */

function readRemarkMessage(remark: string): string {
    const trimmed = remark.trim()
    if (!trimmed) return ""
    try {
        const parsed = JSON.parse(trimmed) as {
            reason?: string
            hits?: Array<{ word?: string }>
            status_message?: string
            exception?: string
            message?: string
            data?: { exception?: string }
        }
        if (parsed.reason === "sensitive_check") {
            const words = (parsed.hits || [])
                .map((hit) => (hit.word || "").trim())
                .filter((word, index, all) => word && all.indexOf(word) === index)
            if (!words.length) return "您上传的文件包含违规内容，请修改后重试"
            return `您上传的文件包含违规内容：{${words.join(",")}}，请修改后重试`
        }
        const nested = parsed.data?.exception || parsed.exception || parsed.message || parsed.status_message
        return typeof nested === "string" ? nested.trim() : trimmed
    } catch {
        return trimmed
    }
}

export function failureReason(status: number, remark: string): string {
    if (status === 6) return readRemarkMessage(remark) || "解析超时"
    if (status === 7) return readRemarkMessage(remark) || "您上传的文件包含违规内容，请修改后重试"
    return readRemarkMessage(remark) || "解析失败"
}
