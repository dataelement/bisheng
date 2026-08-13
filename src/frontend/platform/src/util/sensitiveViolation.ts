/**
 * Content-safety violation state of a knowledge file.
 *
 * The message wording and its locale keys already existed for the knowledge
 * file list, which shows it in a tooltip. They live here so a second surface —
 * the tag console, which has to refuse a preview and explain why — states the
 * same thing rather than inventing a parallel wording that drifts.
 */

/** `knowledge_file.status` for a file that failed the content-safety check. */
export const FILE_STATUS_VIOLATION = 7

type Translate = (key: string, options?: Record<string, any>) => string

export function isViolationFile(file: { status?: number | null }): boolean {
    return file?.status === FILE_STATUS_VIOLATION
}

/**
 * The words that tripped the check, deduplicated and in order.
 *
 * `remark` is JSON for a content-safety rejection and free text for every other
 * failure, so anything unparseable simply yields no words and the caller falls
 * back to the generic message.
 */
export function sensitiveViolationWords(remark?: string | null): string[] {
    const trimmed = remark?.trim()
    if (!trimmed || !trimmed.startsWith("{")) return []
    try {
        const parsed = JSON.parse(trimmed)
        if (parsed?.reason !== "sensitive_check" || !Array.isArray(parsed?.hits)) return []
        const words = parsed.hits.map((hit: any) => String(hit?.word ?? "").trim()).filter(Boolean)
        return words.filter((word: string, index: number) => words.indexOf(word) === index)
    } catch {
        // Not a structured rejection — the generic message is the right answer.
        return []
    }
}

/** Same sentence the knowledge file list shows, with the hit words when known. */
export function sensitiveViolationMessage(remark: string | null | undefined, t: Translate): string {
    const words = sensitiveViolationWords(remark)
    if (!words.length) return t("sensitiveViolationMessage", { ns: "knowledge" })
    return (
        t("sensitiveViolationMessagePrefix", { ns: "knowledge" }) +
        `{${words.join(",")}}` +
        t("sensitiveViolationMessageSuffix", { ns: "knowledge" })
    )
}
