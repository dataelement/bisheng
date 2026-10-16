/**
 * F078: notice codes of a workflow agent node that ran skills, e.g.
 * "code_executor_missing". The backend sends them in the message extra as
 * `{"agent_notices": [...]}`.
 */
export function parseAgentNotices(extra: unknown): string[] {
    let value = extra;
    if (typeof value === "string") {
        if (!value) return [];
        try {
            value = JSON.parse(value);
        } catch {
            return [];
        }
    }
    if (!value || typeof value !== "object") return [];
    const notices = (value as { agent_notices?: unknown }).agent_notices;
    return Array.isArray(notices) ? notices.filter((one): one is string => typeof one === "string") : [];
}
