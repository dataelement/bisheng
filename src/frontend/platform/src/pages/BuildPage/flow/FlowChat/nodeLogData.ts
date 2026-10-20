import type { TFunction } from "i18next";

type LogItem = { key: string, value: unknown, type: string }

interface NodeEndMessage {
    reason?: string | null
    log_data?: LogItem[][] | null
}

// Must match SUBFLOW_ERROR_MARKER in the backend subflow node.
const SUBFLOW_ERROR_MARKER = '-- subflow error --'

/** A subflow failure carries its error code and data after the marker; show it like the run's error toast. */
function readableReason(reason: string, t: TFunction): string {
    const at = reason.indexOf(SUBFLOW_ERROR_MARKER)
    if (at < 0) return reason
    const text = reason.slice(0, at).trim()
    try {
        const error = JSON.parse(reason.slice(at + SUBFLOW_ERROR_MARKER.length))
        return String(t(`api_errors:${error.status_code}`, { ...(error.data || {}), defaultValue: error.status_message || text }))
    } catch {
        return text
    }
}

/**
 * Log rounds shown on a node after it ends. A failed node shows its error first,
 * followed by whatever the node logged before failing (F086: a subflow node's
 * inputs and inner node runs).
 */
export function nodeLogData(message: NodeEndMessage, t: TFunction): LogItem[][] | null | undefined {
    if (!message.reason) return message.log_data
    const logged = (message.log_data || []).flat()
    return [[{ key: 'error', type: 'params', value: readableReason(message.reason, t) }, ...logged]]
}
