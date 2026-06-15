/**
 * ToolCallDisplay — compact horizontal row representing one agent tool call.
 *
 * Inflight  : `⏳ 正在调用 {display_name} 工具` (no chips)
 * Finished  : `✓ 已{动作}{类别} ({N} 个结果)` + inline chip badges for each result
 * Failed    : `⚠️ {display_name} 失败: {error}`
 *
 * 3 variants via `tool_type`:
 *   - "knowledge"   → 「已检索知识 (N 个结果)」, doc-style chips
 *   - "web"         → 「已联网搜索 (N 个结果)」, site-style chips (title + source)
 *   - "tool" (any)  → 「已调用 {display_name} 工具」, brief chips / result preview
 */
import { Outlined } from "bisheng-icons";
import { AlertCircle } from "lucide-react";
import { memo, useEffect, useState, type FC } from "react";
import type { AgentToolCall } from "~/api/chatApi";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

export interface ToolCallDisplayProps {
    toolCall: AgentToolCall;
    /** Whether to render a short vertical timeline connector below this card.
     *  Set to true when this is not the last tool in its group, so a visual
     *  line bridges to the next tool even when both are collapsed. */
    showConnector?: boolean;
}

// --- helpers ---------------------------------------------------------------

function classifyToolType(tc: AgentToolCall): "knowledge" | "web" | "tool" {
    if (tc.tool_type === "knowledge") return "knowledge";
    if (tc.tool_type === "web") return "web";
    // Heuristics for legacy rows / server variants:
    const name = (tc.tool_name || "").toLowerCase();
    if (name.includes("knowledge") || name.includes("kb")) return "knowledge";
    if (name === "web_search" || name.includes("search")) return "web";
    return "tool";
}

// System-managed built-ins get a localized name; everything else falls back
// to whatever the backend advertises (tool.name).
const BUILTIN_TOOL_I18N: Record<string, string> = {
    search_knowledge_bases: "com_tools_knowledge_search",
    web_search: "com_tools_web_search",
};

function resolveToolName(
    tc: AgentToolCall,
    localize: ReturnType<typeof useLocalize>,
): string {
    const key = BUILTIN_TOOL_I18N[(tc.tool_name || "").toLowerCase()];
    if (key) return localize(key);
    return tc.display_name || tc.tool_name || localize("com_tools_generic_fallback");
}

function parseResults(raw: any): any[] {
    if (raw === null || raw === undefined || raw === "") return [];
    if (Array.isArray(raw)) return raw;
    if (typeof raw === "string") {
        try {
            const p = JSON.parse(raw);
            return Array.isArray(p) ? p : [p];
        } catch {
            return [{ text: raw }];
        }
    }
    if (typeof raw === "object") return [raw];
    // Primitives (number / boolean): wrap so the chip can render the value.
    return [{ text: String(raw) }];
}

function extractChipLabel(item: any, variant: string): string {
    if (!item) return "";
    if (typeof item === "string") {
        return item.slice(0, 24);
    }
    if (variant === "web") {
        return (
            item.title ||
            item.name ||
            item.source ||
            (item.url ? safeHostname(item.url) : "网页")
        )
            .toString()
            .slice(0, 24);
    }
    // Generic tool: prefer a human-readable value field before falling back.
    const value =
        item.name ||
        item.title ||
        item.label ||
        item.text ||
        item.output ||
        item.result ||
        item.value ||
        "结果";
    return String(value).slice(0, 48);
}

function safeHostname(url: string): string {
    try { return new URL(url).hostname; } catch { return url; }
}

/**
 * Single web-result chip. Uses the site's own `/favicon.ico` (no third-party
 * favicon service — Google's s2 endpoint is blocked in mainland China), and
 * falls back to the Globe icon on load failure.
 */
const WebResultChip: FC<{ item: any; chip: string }> = ({ item, chip }) => {
    const url = item?.url;
    const host = url ? safeHostname(url) : "";
    const [faviconFailed, setFaviconFailed] = useState(false);
    const showFavicon = !!host && !faviconFailed;

    const content = (
        <span
            className="inline-flex items-center gap-1 rounded-[4px] bg-[#F7F7F7] px-2 py-[2px] text-xs leading-5 text-[#1D2129]"
            title={chip}
        >
            {showFavicon ? (
                <span className="flex size-4 shrink-0 items-center justify-center overflow-hidden rounded-full border-[0.5px] border-[#ECECEC] bg-white">
                    <img
                        src={`https://${host}/favicon.ico`}
                        alt=""
                        className="size-[14px]"
                        onError={() => setFaviconFailed(true)}
                    />
                </span>
            ) : (
                <Outlined.Earth size={16} className="shrink-0 text-[#6B7785]" />
            )}
            <span className="max-w-[120px] truncate">{chip}</span>
        </span>
    );

    return url ? (
        <a href={url} target="_blank" rel="noreferrer" className="no-underline hover:opacity-80">
            {content}
        </a>
    ) : (
        content
    );
};

/** For web results: dedupe by hostname (or title if no url), preserve search-result order. */
function normaliseWebResults(items: any[]): any[] {
    const seen = new Set<string>();
    const out: any[] = [];
    for (const raw of items) {
        if (!raw) continue;
        const item = typeof raw === "string" ? { title: raw } : raw;
        const host = item.url ? safeHostname(item.url) : "";
        const key = host || (item.title || item.name || "").toString();
        if (!key) continue;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(item);
    }
    return out;
}

/**
 * Knowledge results arrive as opaque chunk strings tagged with
 * `<knowledge_base_id>` / `<knowledge_base_name>` (emitted by the backend
 * `_format_chunk`). The UI shows one chip per knowledge base in the order the
 * model first cited it — not one chip per chunk/file — per v2.5 spec §3.1.
 *
 * Backend also emits synthetic chunks for failed KBs carrying
 * `<retrieval_error>...</retrieval_error>` so the UI can surface the failure
 * inline with the successful chips instead of dropping them silently.
 */
function normaliseKnowledgeResults(
    items: any[],
): { id: string; name: string; error?: string }[] {
    const seen = new Map<string, { id: string; name: string; error?: string }>();
    const order: string[] = [];
    for (const raw of items) {
        if (!raw) continue;
        const text =
            typeof raw === "string"
                ? raw
                : (raw.chunk || raw.text || raw.content || "").toString();
        const idMatch = /<knowledge_base_id>([^<]*)<\/knowledge_base_id>/.exec(text);
        const nameMatch = /<knowledge_base_name>([^<]*)<\/knowledge_base_name>/.exec(text);
        const errMatch = /<retrieval_error>([\s\S]*?)<\/retrieval_error>/.exec(text);
        const id = (idMatch?.[1] || "").trim();
        const name = (nameMatch?.[1] || "").trim();
        const error = errMatch ? errMatch[1].trim() : undefined;
        // Fall back to file_title / object fields when the chunk lacks KB tags
        // (e.g. legacy rows persisted before the backend started embedding them).
        const fallbackName = !name
            ? (() => {
                const ft = /<file_title>([^<]+)<\/file_title>/.exec(text)?.[1];
                if (ft) return ft.trim();
                if (typeof raw === "object") {
                    return (
                        raw.knowledge_base_name ||
                        raw.kb_name ||
                        raw.file_title ||
                        raw.title ||
                        ""
                    ).toString();
                }
                return "";
            })()
            : name;
        const finalName = fallbackName || "知识库";
        const key = id || finalName;
        const existing = seen.get(key);
        if (existing) {
            // A successful chunk takes precedence over a prior error entry;
            // otherwise keep the first seen entry.
            if (existing.error && !error) {
                existing.error = undefined;
            }
            continue;
        }
        seen.set(key, { id, name: finalName, error });
        order.push(key);
    }
    return order.map((k) => seen.get(k)!).filter(Boolean);
}

// --- component -------------------------------------------------------------

const variantStyles = {
    knowledge: {
        icon: <Outlined.BookOpenText size={16} className="shrink-0 text-[#C9CDD4]" />,
    },
    web: {
        icon: <Outlined.Earth size={16} className="shrink-0 text-[#C9CDD4]" />,
    },
    tool: {
        icon: <Outlined.Hammer size={16} className="shrink-0 text-[#C9CDD4]" />,
    },
} as const;

const ToolCallDisplay: FC<ToolCallDisplayProps> = memo(({ toolCall, showConnector = false }) => {
    const localize = useLocalize();
    const variant = classifyToolType(toolCall);
    const rawResults = toolCall.error ? [] : parseResults(toolCall.results);
    // Per v2.5 spec §3:
    //   knowledge → group/dedupe by KB (one chip per knowledge base)
    //   web       → dedupe by hostname, default expanded
    //   tool      → no result list; pill only conveys "已使用 {name}"
    const knowledgeChips =
        variant === "knowledge" ? normaliseKnowledgeResults(rawResults) : [];
    const webResults = variant === "web" ? normaliseWebResults(rawResults) : [];
    const resultCount =
        variant === "knowledge"
            ? knowledgeChips.length
            : variant === "web"
                ? webResults.length
                : 0;
    const name = resolveToolName(toolCall, localize);
    const label = (() => {
        if (variant === "knowledge") {
            if (toolCall.inflight) return "正在检索知识";
            if (toolCall.error) return "检索知识失败";
            return "已检索知识";
        }
        if (variant === "web") {
            if (toolCall.inflight) return "正在联网搜索";
            if (toolCall.error) return "联网搜索失败";
            return "已联网搜索";
        }
        if (toolCall.inflight) return `正在调用 ${name}`;
        if (toolCall.error) return `${name} 失败`;
        return `已使用 ${name}`;
    })();
    const style = variantStyles[variant];
    // Panel only renders when there is actual content: errors, or finished
    // knowledge/web variants with results. Inflight no longer surfaces raw
    // args JSON, so the panel would otherwise be an empty gap.
    const hasDetails =
        !!toolCall.error ||
        (!toolCall.inflight && variant !== "tool" && resultCount > 0);

    // Web variant stays open by default after finish (spec §3.2.4); errors
    // stay open to surface the message; knowledge variant auto-expands when
    // any KB failed so the error detail is visible without another click.
    const hasKnowledgeErrors =
        variant === "knowledge" && knowledgeChips.some((kb) => kb.error);
    const initialExpanded =
        !!toolCall.error ||
        hasKnowledgeErrors ||
        (variant === "web" && !toolCall.inflight);
    const [expanded, setExpanded] = useState<boolean>(initialExpanded);
    useEffect(() => {
        if (toolCall.error) {
            setExpanded(true);
        } else if (hasKnowledgeErrors) {
            setExpanded(true);
        } else if (variant === "web" && !toolCall.inflight) {
            setExpanded(true);
        } else {
            setExpanded(false);
        }
    }, [toolCall.inflight, toolCall.error, variant, hasKnowledgeErrors]);

    const railIcon = toolCall.inflight ? (
        <Outlined.Loading size={16} className="shrink-0 animate-spin text-primary" />
    ) : toolCall.error ? (
        <AlertCircle size={16} className="shrink-0 text-red-500" />
    ) : (
        style.icon
    );

    return (
        <div className="flex w-full min-w-0 gap-1.5">
            <div className="flex shrink-0 flex-col items-center gap-0.5 self-stretch pt-[3px]">
                {railIcon}
                {/* Rail line: keep the timeline continuous to the next node, and
                    always flank this node's own expanded content. */}
                {(showConnector || expanded) && (
                    <div className="w-px flex-1 bg-[#E0E0E0]" aria-hidden="true" />
                )}
            </div>
            <div className="flex min-w-0 flex-1 flex-col pb-3">
                <button
                    type="button"
                    onClick={hasDetails && !toolCall.inflight ? () => setExpanded((v) => !v) : undefined}
                    disabled={!hasDetails || toolCall.inflight}
                    className={cn(
                        "group flex w-fit max-w-full items-center gap-1 text-sm leading-[22px] text-[#999999]",
                        hasDetails && !toolCall.inflight && "transition-colors hover:text-[#212121]",
                        toolCall.inflight && "animate-pulse",
                    )}
                >
                    <span>{label}</span>
                    {!toolCall.inflight &&
                        !toolCall.error &&
                        variant !== "tool" &&
                        resultCount > 0 && (
                            <span>
                                （{localize("com_tools_result_count", { count: resultCount })}）
                            </span>
                        )}
                    {hasDetails && !toolCall.inflight && (
                        <Outlined.Down
                            size={16}
                            className={cn(
                                "shrink-0 transform-gpu transition-transform duration-200",
                                expanded && "rotate-180",
                            )}
                        />
                    )}
                </button>
                <div
                    className={cn("grid transition-all duration-300 ease-out", expanded && "mt-2")}
                    style={{ gridTemplateRows: expanded ? "1fr" : "0fr" }}
                >
                    <div className="overflow-hidden min-h-0 text-xs text-text-secondary">
                        {toolCall.error && (
                            <div className="leading-[22px]">{toolCall.error}</div>
                        )}

                        {!toolCall.inflight && !toolCall.error && variant === "knowledge" && knowledgeChips.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                                {knowledgeChips.map((kb, i) => (
                                    <span
                                        key={kb.id || `${kb.name}-${i}`}
                                        className={cn(
                                            "inline-flex items-center gap-1 rounded-[4px] px-2 py-[2px] text-xs leading-5",
                                            kb.error
                                                ? "bg-red-50 text-red-600 dark:bg-red-950/30 dark:text-red-300"
                                                : "bg-[#F7F7F7] text-[#1D2129]",
                                        )}
                                        title={kb.error ? `${kb.name} 检索失败：${kb.error}` : kb.name}
                                    >
                                        {kb.error ? (
                                            <AlertCircle className="size-[14px] shrink-0 text-red-500" />
                                        ) : (
                                            <Outlined.BookOpenText size={14} className="shrink-0 text-[#6B7785]" />
                                        )}
                                        <span className="max-w-[120px] truncate">{kb.name}</span>
                                    </span>
                                ))}
                            </div>
                        )}

                        {!toolCall.inflight && !toolCall.error && variant === "web" && webResults.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                                {webResults.map((item, i) => (
                                    <WebResultChip
                                        key={i}
                                        item={item}
                                        chip={extractChipLabel(item, variant)}
                                    />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
});

ToolCallDisplay.displayName = "ToolCallDisplay";

export default ToolCallDisplay;
