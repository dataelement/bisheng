/**
 * Activity summary: classify a group's tool calls into readable buckets.
 * Split out of stepUtils.ts.
 */
import { INGEST_STEP_NAME } from './execTypes';
import type { MergedStep } from './execTypes';

/**
 * (Activity §3) The readable activity categories — one localized "动作摘要" verb
 * phrase each. `other` is the catch-all bucket for unknown MCP tools. The i18n
 * key for each lives in execTokens.ts (ACTIVITY_I18N), kept here only as the
 * category vocabulary so summarizeActivity stays pure / i18n-free.
 */
export type ActivityCategory =
    | 'web_search'
    | 'knowledge'
    | 'read_file'
    | 'write_file'
    | 'export'
    | 'code'
    | 'browse'
    | 'other';

/** One readable activity bucket: a category + how many times it fired. */
export interface ActivityCount {
    category: ActivityCategory;
    count: number;
}

/**
 * Classify a tool name (lowercased) into an ActivityCategory per spec §3. Order
 * matters: knowledge/search is checked before the generic `search` so that
 * `search_knowledge_base` lands in `knowledge`, not `web_search`. Returns null
 * for names that should never count (caller already excludes thinking/ls/
 * write_todos/ask_user, but this guards defensively).
 */
function classifyActivity(name: string): ActivityCategory | null {
    const n = name.toLowerCase();
    if (!n) return 'other';
    // never-count noise (defensive — callers already drop these)
    if (n === 'thinking' || n === 'ls' || n === 'write_todos' || n === 'ask_user') return null;
    // Attachment ingest is the SYSTEM preparing the user's uploads, not the agent
    // acting. Counting it charged the agent for the whole parse — a 12-PDF batch
    // turned the header into "读取 6 个文件 · 执行 1 步操作（用时 1416 秒）", i.e.
    // 20 minutes of file parsing billed to the model's thinking. It renders as its
    // own phase row (IngestPhaseRow) and is deliberately absent from the tally.
    if (n === INGEST_STEP_NAME) return null;
    // knowledge before web_search: search_knowledge_base must not match web_search
    if (n.includes('knowledge') || n.includes('search_knowledge')) return 'knowledge';
    if (n.includes('web_search') || n.includes('search')) return 'web_search';
    if (n.includes('export')) return 'export';
    // write/edit family before read so `read` doesn't swallow add_text_to_file etc.
    if (
        n.includes('write_file') ||
        n.includes('add_text_to_file') ||
        n.includes('replace_file_lines') ||
        n.includes('write') ||
        n.includes('edit')
    ) {
        return 'write_file';
    }
    if (n.includes('read_file') || n.includes('read')) return 'read_file';
    if (n.includes('code_interpreter') || n.includes('python') || n.includes('code')) return 'code';
    if (n.includes('glob') || n.includes('grep')) return 'browse';
    return 'other';
}

/**
 * (Activity §3) Summarize a group of steps into readable activity counts. Walks
 * the steps, excludes thinking / ls / write_todos / ask_user, classifies the
 * rest by tool name (classifyActivity), and returns the categories sorted by
 * count descending. Empty input (or a pure-thinking group) returns []. Pure —
 * no i18n; the caller maps category → localized phrase via ACTIVITY_I18N.
 */
export function summarizeActivity(steps: MergedStep[] | null | undefined): ActivityCount[] {
    const counts = new Map<ActivityCategory, number>();
    (steps || []).forEach((step) => {
        // thinking is never an activity; call_user_input is a boundary (an inline
        // IntentRow, never part of an episode) — defensive so it can never be
        // miscounted as `other` (its empty name would otherwise classify there).
        if (!step || step.stepType === 'thinking' || step.stepType === 'call_user_input') return;
        const category = classifyActivity(step.name || '');
        if (!category) return;
        counts.set(category, (counts.get(category) || 0) + 1);
    });
    return Array.from(counts.entries())
        .map(([category, count]) => ({ category, count }))
        .sort((a, b) => b.count - a.count);
}
