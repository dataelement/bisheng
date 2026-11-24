/**
 * One knowledge search = one row in the deep-thinking timeline.
 *
 * Rows are never merged, so the real order of search and thinking is kept. To
 * tell rows apart when collapsed, each row shows its query and hit count, with
 * the knowledge base name as a small chip at the end. Only fields the backend already sends are used:
 * `tool_call_id`, `args.query`, `args.knowledge_base_ids` and the tagged chunk
 * strings in `results`.
 */
import type { AgentEvent, AgentToolCall } from "~/api/chatApi";

export interface KnowledgeCallInfo {
    /** Knowledge bases searched, order-insensitive identity (ids, or names when ids are missing). */
    kbKeys: string[];
    /** Display names for those knowledge bases; empty when none is known yet. */
    kbNames: string[];
    /** Trimmed query text as sent by the model. */
    query: string;
    /** Query with repeated words removed, as shown in the row. */
    displayQuery: string;
    /** False when the query looks like search syntax and must not be shown. */
    queryReadable: boolean;
    /** Chunks returned by this call across all knowledge bases. */
    chunkCount: number;
    /** Distinct document titles, in first-seen order. */
    docs: string[];
    /** True when at least one knowledge base returned a retrieval error. */
    hasError: boolean;
}

export interface KnowledgeRowContext {
    /** 1-based position among knowledge searches of this deep-thinking run. */
    ordinal: number;
}

export interface KnowledgeRowPlan {
    /** Keyed by the event index of each knowledge search. */
    rows: Map<number, KnowledgeRowContext>;
    /** Knowledge base id -> name, collected from every result in the run. */
    kbNameById: Record<string, string>;
}

/** Same heuristics ToolCallDisplay used to pick the knowledge variant. */
export function isKnowledgeToolCall(tc: AgentToolCall): boolean {
    if (tc.tool_type === "knowledge") return true;
    if (tc.tool_type === "web") return false;
    const name = (tc.tool_name || "").toLowerCase();
    return name.includes("knowledge") || name.includes("kb");
}

/** Longer queries are treated as unreadable and hidden. */
export const MAX_READABLE_QUERY_LENGTH = 40;

const UNREADABLE_QUERY_PATTERNS: RegExp[] = [
    /\b(?:AND|OR|NOT)\b/, // boolean operators (upper case only, so plain English "or" stays readable)
    /[\^*~]/, // boost / wildcard / fuzzy operators
    /\([^)]*\)|\[[^\]]*\]|\{[^}]*\}/, // paired ASCII brackets
    /[A-Za-z_][\w.]*:\S/, // field:value
];

/**
 * Front-end fallback for model-written queries. Queries that look like search
 * syntax rather than a phrase a person would read are not shown.
 */
export function isReadableKnowledgeQuery(query: string): boolean {
    const text = (query ?? "").trim();
    if (!text) return false;
    // Keep this length guard before the patterns: the bracket pattern backtracks
    // quadratically on long unmatched input.
    if (text.length > MAX_READABLE_QUERY_LENGTH) return false;
    return !UNREADABLE_QUERY_PATTERNS.some((pattern) => pattern.test(text));
}

/**
 * Space-separated words of a model-written query often repeat ("价值 总结 价值").
 * Keep each word once, in first-seen order, joined by a single space.
 */
export function compactKnowledgeQuery(query: string): string {
    const seen = new Set<string>();
    const words: string[] = [];
    for (const word of (query ?? "").split(/[\s\u3000]+/)) {
        if (!word) continue;
        const key = word.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        words.push(word);
    }
    return words.join(" ");
}

/**
 * Id -> name of the knowledge bases the user selected in the input bar. Both
 * kinds (document knowledge bases and knowledge spaces) share one id space in
 * the `knowledge_base_ids` the model sends, so one map serves both.
 */
export function knownKnowledgeBaseNames(
    selected: ReadonlyArray<{ id?: string | number; name?: string; type?: string }> | undefined,
): Record<string, string> {
    const names: Record<string, string> = {};
    for (const item of selected ?? []) {
        const id = String(item?.id ?? "");
        if (id && item?.name) names[id] = item.name;
    }
    return names;
}

/** Names to show for a knowledge base list: up to two, otherwise the first plus a total. */
export function summariseKnowledgeBaseNames(names: string[]): { shown: string[]; total: number } {
    const total = names.length;
    return { shown: total <= 2 ? [...names] : names.slice(0, 1), total };
}

interface ParsedHit {
    kbId: string;
    kbName: string;
    chunks: { title: string }[];
    error: boolean;
}

function parseResults(raw: unknown): unknown[] {
    if (raw === null || raw === undefined || raw === "") return [];
    if (Array.isArray(raw)) return raw;
    if (typeof raw === "string") {
        try {
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [parsed];
        } catch {
            return [raw];
        }
    }
    return [raw];
}

function tag(text: string, name: string): string {
    return (new RegExp(`<${name}>([\\s\\S]*?)</${name}>`).exec(text)?.[1] ?? "").trim();
}

/** Group the tagged chunk strings of one call by knowledge base. */
function parseHits(tc: AgentToolCall): Map<string, ParsedHit> {
    const hits = new Map<string, ParsedHit>();
    for (const raw of parseResults(tc.results)) {
        if (!raw) continue;
        const item = raw as Record<string, unknown>;
        const text = typeof raw === "string" ? raw : String(item.chunk || item.text || item.content || "");
        const kbId = tag(text, "knowledge_base_id");
        const kbName = tag(text, "knowledge_base_name");
        if (!kbId && !kbName) continue;
        const key = kbId || kbName;
        let hit = hits.get(key);
        if (!hit) {
            hit = { kbId, kbName, chunks: [], error: false };
            hits.set(key, hit);
        }
        if (!hit.kbName && kbName) hit.kbName = kbName;
        if (/<retrieval_error>/.test(text)) hit.error = true;
        else hit.chunks.push({ title: tag(text, "file_title") });
    }
    return hits;
}

function searchedKnowledgeBaseIds(tc: AgentToolCall): string[] {
    const ids = tc.args?.knowledge_base_ids;
    return Array.isArray(ids) ? ids.map((id) => String(id)).filter(Boolean) : [];
}

export function describeKnowledgeCall(
    tc: AgentToolCall,
    kbNameById: Record<string, string>,
): KnowledgeCallInfo {
    const hits = parseHits(tc);
    const argIds = searchedKnowledgeBaseIds(tc);
    const kbKeys = argIds.length > 0 ? argIds : [...hits.keys()];

    const kbNames: string[] = [];
    for (const key of kbKeys) {
        const name = kbNameById[key] || hits.get(key)?.kbName || "";
        if (name && !kbNames.includes(name)) kbNames.push(name);
    }

    const docs: string[] = [];
    let chunkCount = 0;
    let hasError = false;
    hits.forEach((hit) => {
        chunkCount += hit.chunks.length;
        hasError = hasError || hit.error;
        for (const { title } of hit.chunks) {
            if (title && !docs.includes(title)) docs.push(title);
        }
    });

    const query = String(tc.args?.query ?? "").trim();
    return { kbKeys, kbNames, query, displayQuery: compactKnowledgeQuery(query), queryReadable: isReadableKnowledgeQuery(query), chunkCount, docs, hasError };
}

/**
 * Knowledge base ids the model searched in this run that no name is known for,
 * neither from `knownNames` nor from the result strings. These are looked up by
 * id (see useKnowledgeBaseNames). Each id once, in first-seen order.
 */
export function unnamedKnowledgeBaseIds(
    events: AgentEvent[],
    knownNames: Record<string, string> = {},
): string[] {
    const named = planKnowledgeRows(events, knownNames).kbNameById;
    const ids: string[] = [];
    for (const ev of events) {
        if (ev.type !== "tool_call" || !isKnowledgeToolCall(ev)) continue;
        for (const id of searchedKnowledgeBaseIds(ev)) {
            if (!named[id] && !ids.includes(id)) ids.push(id);
        }
    }
    return ids;
}

/**
 * Number every knowledge search of one deep-thinking run (1-based) and collect
 * the knowledge base names seen in the results, so a search that is still
 * running can already show its knowledge base. Rows are never merged or
 * shortened: search and thinking keep their real order. A call that failed as a
 * whole gets no row and is rendered by the generic tool-call display.
 */
export function planKnowledgeRows(
    events: AgentEvent[],
    knownNames: Record<string, string> = {},
): KnowledgeRowPlan {
    // Names from the user's selection come first, so a searched knowledge base
    // that returned no chunk (and so is never named in the results) still gets
    // a label. A name carried by a result overrides the selection below.
    const kbNameById: Record<string, string> = { ...knownNames };
    for (const ev of events) {
        if (ev.type !== "tool_call" || !isKnowledgeToolCall(ev)) continue;
        parseHits(ev).forEach((hit) => {
            if (hit.kbId && hit.kbName) kbNameById[hit.kbId] = hit.kbName;
        });
    }

    const rows = new Map<number, KnowledgeRowContext>();
    let ordinal = 0;
    events.forEach((ev, index) => {
        if (ev.type !== "tool_call" || !isKnowledgeToolCall(ev)) return;
        // The backend also sets error/failure_info on the call for a single failed
        // knowledge base, so those flags alone do not mean the whole call failed.
        // Only a call that produced no knowledge base result goes to the generic display.
        if ((ev.error || ev.failure_info) && parseHits(ev).size === 0) return;
        ordinal += 1;
        rows.set(index, { ordinal });
    });
    return { rows, kbNameById };
}
