type LogItem = { key: string, value: unknown, type: string }

interface NodeEndMessage {
    reason?: string | null
    log_data?: LogItem[][] | null
}

/**
 * Log rounds shown on a node after it ends. A failed node shows its error first,
 * followed by whatever the node logged before failing (F086: a subflow node's
 * inputs and inner node runs).
 */
export function nodeLogData(message: NodeEndMessage): LogItem[][] | null | undefined {
    if (!message.reason) return message.log_data
    const logged = (message.log_data || []).flat()
    return [[{ key: 'error', type: 'params', value: message.reason }, ...logged]]
}
