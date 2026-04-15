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
import { AlertCircle, BookOpen, ChevronDown, Globe, Hammer, Loader2 } from "lucide-react";
import { memo, useEffect, useState, type FC } from "react";
import type { AgentToolCall } from "~/api/chatApi";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";

export interface ToolCallDisplayProps {
    toolCall: AgentToolCall;
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
 */
function normaliseKnowledgeResults(items: any[]): { id: string; name: string }[] {
    const seen = new Set<string>();
    const out: { id: string; name: string }[] = [];
    for (const raw of items) {
        if (!raw) continue;
        const text =
            typeof raw === "string"
                ? raw
                : (raw.chunk || raw.text || raw.content || "").toString();
        const idMatch = /<knowledge_base_id>([^<]*)<\/knowledge_base_id>/.exec(text);
        const nameMatch = /<knowledge_base_name>([^<]*)<\/knowledge_base_name>/.exec(text);
        const id = (idMatch?.[1] || "").trim();
        const name = (nameMatch?.[1] || "").trim();
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
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ id, name: finalName });
    }
    return out;
}

// --- component -------------------------------------------------------------

const variantStyles = {
    knowledge: {
        pill: "bg-blue-50 text-blue-700 border-blue-100 dark:bg-blue-950/40 dark:text-blue-300",
        icon: <BookOpen className="size-3.5" />,
    },
    web: {
        pill: "bg-purple-50 text-purple-700 border-purple-100 dark:bg-purple-950/40 dark:text-purple-300",
        icon: <Globe className="size-3.5" />,
    },
    tool: {
        pill: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-800/60 dark:text-slate-200",
        icon: <Hammer className="size-3.5" />,
    },
} as const;

function formatArgs(args: unknown): string {
    if (args == null) return "";
    if (typeof args === "string") return args.slice(0, 120);
    try {
        const s = JSON.stringify(args);
        return s.length > 120 ? `${s.slice(0, 120)}…` : s;
    } catch {
        return "";
    }
}

const ToolCallDisplay: FC<ToolCallDisplayProps> = memo(({ toolCall }) => {
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
    // Generic "tool" variant intentionally hides results this release; only
    // knowledge / web have an expandable detail panel.
    const hasDetails =
        toolCall.inflight ||
        !!toolCall.error ||
        (variant !== "tool" && resultCount > 0);

    // Inflight: always expanded. Finished: web stays open by default (spec
    // §3.2.4), knowledge stays collapsed for compactness, tool has no panel.
    const initialExpanded = !!toolCall.inflight || variant === "web";
    const [expanded, setExpanded] = useState<boolean>(initialExpanded);
    useEffect(() => {
        if (toolCall.inflight) {
            setExpanded(true);
        } else if (variant === "web") {
            setExpanded(true);
        } else {
            setExpanded(false);
        }
    }, [toolCall.inflight, variant]);

    const argsPreview = toolCall.inflight ? formatArgs(toolCall.args) : "";

    const leadingIcon = toolCall.inflight ? (
        <Loader2 className="mr-1.5 size-3.5 animate-spin text-text-secondary" />
    ) : toolCall.error ? (
        <AlertCircle className="mr-1.5 size-3.5 text-red-500" />
    ) : (
        <span className="mr-1.5 text-text-secondary">{style.icon}</span>
    );

    const pill = (
        <button
            type="button"
            onClick={hasDetails && !toolCall.inflight ? () => setExpanded((v) => !v) : undefined}
            disabled={!hasDetails || toolCall.inflight}
            className={cn(
                "group mt-3 flex w-fit items-center justify-center rounded-xl bg-surface-tertiary px-3 py-2 text-xs leading-[18px]",
                toolCall.inflight && "animate-pulse",
            )}
        >
            {leadingIcon}
            <span>{label}</span>
            {!toolCall.inflight &&
                !toolCall.error &&
                variant !== "tool" &&
                resultCount > 0 && (
                    <span className="ml-1 text-text-secondary">({resultCount})</span>
                )}
            {hasDetails && !toolCall.inflight && (
                <ChevronDown
                    className={cn(
                        "icon-sm ml-1.5 transform-gpu text-text-primary transition-transform duration-200",
                        expanded && "rotate-180",
                    )}
                />
            )}
        </button>
    );

    return (
        <>
            {pill}
            <div
                className={cn(
                    "grid transition-all duration-300 ease-out",
                    expanded && "mb-4",
                )}
                style={{ gridTemplateRows: expanded ? "1fr" : "0fr" }}
            >
                <div className="overflow-hidden mt-3">
                    <div className="relative pl-3 text-xs text-text-secondary">
                        <div className="absolute left-0 h-full border-l-2 border-border-medium dark:border-border-heavy" />

                        {toolCall.error && (
                            <div className="leading-[22px]">{toolCall.error}</div>
                        )}

                        {toolCall.inflight && argsPreview && (
                            <div className="font-mono text-[11px] leading-[22px]">
                                {argsPreview}
                            </div>
                        )}

                        {!toolCall.inflight && !toolCall.error && variant === "knowledge" && knowledgeChips.length > 0 && (
                            <div className="flex flex-wrap gap-1.5">
                                {knowledgeChips.map((kb, i) => (
                                    <span
                                        key={kb.id || `${kb.name}-${i}`}
                                        className={cn(
                                            "inline-flex items-center gap-1 rounded-md border px-2 py-0.5",
                                            style.pill,
                                        )}
                                        title={kb.name}
                                    >
                                        {style.icon}
                                        <span className="truncate max-w-[14rem]">{kb.name}</span>
                                    </span>
                                ))}
                            </div>
                        )}

                        {!toolCall.inflight && !toolCall.error && variant === "web" && webResults.length > 0 && (
                            <div className="flex flex-wrap gap-1.5">
                                {webResults.map((item, i) => {
                                    const chip = extractChipLabel(item, variant);
                                    const url = item?.url;
                                    const host = url ? safeHostname(url) : "";
                                    const favicon = host
                                        ? `https://www.google.com/s2/favicons?domain=${host}&sz=32`
                                        : "";
                                    const content = (
                                        <span
                                            className={cn(
                                                "inline-flex items-center gap-1 rounded-md border px-2 py-0.5",
                                                style.pill,
                                            )}
                                            title={chip}
                                        >
                                            {favicon ? (
                                                <img
                                                    src={favicon}
                                                    alt=""
                                                    className="size-3.5 rounded-sm"
                                                    onError={(e) => ((e.currentTarget as HTMLImageElement).style.display = "none")}
                                                />
                                            ) : (
                                                style.icon
                                            )}
                                            <span className="truncate max-w-[14rem]">{chip}</span>
                                        </span>
                                    );
                                    return url ? (
                                        <a
                                            key={i}
                                            href={url}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="no-underline hover:opacity-80"
                                        >
                                            {content}
                                        </a>
                                    ) : (
                                        <span key={i}>{content}</span>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </>
    );
});

ToolCallDisplay.displayName = "ToolCallDisplay";

export default ToolCallDisplay;
