/**
 * F078: deliverable files and notices of a workflow agent node that ran skills.
 *
 * The backend stores each deliverable as `{ file_id, file_name, file_url, format_error? }`.
 * The chat file card reads `{ name, path }`, the shape output-node files already use.
 */

export interface ChatFileItem {
    name: string;
    path: string;
    format_error?: string;
}

interface DeliverableLike {
    name?: string;
    path?: string;
    file_name?: string;
    file_url?: string;
    format_error?: string;
}

export function toChatFiles(files: unknown): ChatFileItem[] {
    if (!Array.isArray(files)) return [];
    return files
        .filter((one): one is DeliverableLike => !!one && typeof one === "object")
        .map((one) => ({
            name: one.name || one.file_name || "",
            path: one.path || one.file_url || "",
            ...(one.format_error ? { format_error: one.format_error } : {}),
        }))
        .filter((one) => one.path);
}

/** Notice codes travel in the message extra as `{"agent_notices": [...]}`. */
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

/** Tool names a skill run adds; the run log shows readable names for them. */
export const AGENT_SKILL_TOOL_NAMES = [
    "ls",
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "bisheng_code_interpreter",
] as const;
