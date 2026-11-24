/**
 * KnowledgeSearchRow — one knowledge search in the deep-thinking timeline.
 *
 * Collapsed : one line, `检索：{检索词} · N 条 [知识库] ⌄`. The query is truncated;
 *             the count, the knowledge base chip(s) and the chevron always stay
 *             visible. The full line is also the hover text.
 * Expanded  : only what the line does not already say — the document chips
 *             (first 3 shown, the rest folded into `+K`), or the failure /
 *             no-hit note.
 *
 * Visual encoding, one per kind of information (matches the citation panel):
 *   action    — magnifier icon on the rail
 *   keyword   — plain text, darker than its label
 *   knowledge — grey chip with the book icon, at the end of the line
 *   document  — grey chip with the file name only: no icon, no border
 *
 * Rows are never merged, so search and thinking keep their real order.
 */
import { Outlined } from "bisheng-icons";
import { AlertCircle } from "lucide-react";
import { memo, useState, type FC } from "react";
import type { AgentToolCall } from "~/api/chatApi";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import {
    describeKnowledgeCall,
    summariseKnowledgeBaseNames,
    type KnowledgeRowContext,
} from "./knowledgeRow";

/** Document chips shown before the rest fold into "+K". */
export const MAX_VISIBLE_DOC_CHIPS = 3;

/** Knowledge base: grey chip with the book icon. */
const kbChipClass = (failed: boolean) =>
    cn(
        "inline-flex shrink-0 items-center gap-1 rounded-sm px-2 py-[2px] text-xs leading-5",
        failed ? "bg-red-50 text-red-600" : "bg-[#F7F7F7] text-text-1",
    );

/** Document: plain grey chip with the file name. No icon, so it never competes with the knowledge base chip. */
const DOC_CHIP_CLASS =
    "inline-flex items-center gap-1 rounded-sm bg-[#F7F7F7] px-2 py-[2px] text-xs leading-5 text-text-1";

export interface KnowledgeSearchRowProps {
    toolCall: AgentToolCall;
    context: KnowledgeRowContext;
    /** Knowledge base id -> name collected from the whole run. */
    kbNameById: Record<string, string>;
    showConnector?: boolean;
}

const KnowledgeSearchRow: FC<KnowledgeSearchRowProps> = memo(
    ({ toolCall, context, kbNameById, showConnector = false }) => {
        const localize = useLocalize();
        const info = describeKnowledgeCall(toolCall, kbNameById);
        const running = !!toolCall.inflight;
        const allFailed = info.hasError && info.chunkCount === 0;
        const [expanded, setExpanded] = useState<boolean>(info.hasError);
        const [showAllDocs, setShowAllDocs] = useState(false);

        const { shown, total } = summariseKnowledgeBaseNames(info.kbNames);
        const kbLabel =
            total === 0
                ? ""
                : total > 2
                    ? localize("com_tools.knowledge_kb_more", { 0: shown[0], 1: total })
                    : shown.join(localize("com_tools.knowledge_kb_sep"));

        // An unreadable query is replaced by the run ordinal so rows still differ.
        const queryText = info.queryReadable
            ? info.displayQuery
            : localize("com_tools.knowledge_row_ordinal", { 0: context.ordinal });
        const label = localize(running ? "com_tools.knowledge_row_label_running" : "com_tools.knowledge_row_label");
        const keyword = running ? `${queryText}...` : queryText;

        const chunkText = localize("com_tools.knowledge_chunk_count", { 0: info.chunkCount });
        const suffix = running
            ? ""
            : allFailed
                ? localize("com_tools.knowledge_query_failed")
                : info.hasError
                    ? `${chunkText} · ${localize("com_tools.knowledge_partial_failed")}`
                    : chunkText;

        const docs = showAllDocs ? info.docs : info.docs.slice(0, MAX_VISIBLE_DOC_CHIPS);
        const hiddenDocCount = info.docs.length - docs.length;
        const hasDetails = !running;
        const hoverText = [`${label}${keyword}`, suffix, kbLabel].filter(Boolean).join(" · ");

        const railIcon = running ? (
            <Outlined.Loading size={16} className="shrink-0 animate-spin text-primary" />
        ) : allFailed ? (
            <AlertCircle size={16} className="shrink-0 text-red-500" />
        ) : (
            <Outlined.Search size={16} className="shrink-0 text-text-3" />
        );

        return (
            <div className="flex w-full min-w-0 gap-1.5">
                <div className="flex shrink-0 flex-col items-center gap-2 self-stretch pt-[3px]">
                    {railIcon}
                    {(showConnector || expanded) && (
                        <div className="w-px flex-1 bg-[#E0E0E0]" aria-hidden="true" />
                    )}
                </div>
                <div className="flex min-w-0 flex-1 flex-col pb-3">
                    <button
                        type="button"
                        onClick={hasDetails ? () => setExpanded((v) => !v) : undefined}
                        disabled={!hasDetails}
                        aria-expanded={hasDetails ? expanded : undefined}
                        title={hoverText}
                        className={cn(
                            "group flex min-w-0 max-w-full items-center gap-1 text-left text-sm leading-[22px] text-text-3",
                            running && "animate-pulse",
                        )}
                    >
                        <span className="shrink-0 whitespace-nowrap">{label}</span>
                        <span className="min-w-0 truncate text-text-1">{keyword}</span>
                        {suffix && <span className="shrink-0 whitespace-nowrap">{`· ${suffix}`}</span>}
                        {shown.map((name) => (
                            <span key={name} className={kbChipClass(allFailed)} title={name}>
                                <Outlined.BookOpenText size={14} className="shrink-0 text-[#6B7785]" />
                                <span className="max-w-[140px] truncate">{name}</span>
                            </span>
                        ))}
                        {total > 2 && (
                            <span className={kbChipClass(allFailed)} title={kbLabel}>
                                {localize("com_tools.knowledge_doc_more", { 0: total - 1 })}
                            </span>
                        )}
                        {hasDetails && (
                            <Outlined.Down
                                size={16}
                                className={cn(
                                    "shrink-0 transform-gpu transition-transform duration-200",
                                    !expanded && "-rotate-90",
                                )}
                            />
                        )}
                    </button>
                    <div
                        className={cn("grid transition-all duration-300 ease-out", expanded && "mt-2")}
                        style={{ gridTemplateRows: expanded ? "1fr" : "0fr" }}
                    >
                        <div className="min-h-0 overflow-hidden text-xs text-text-secondary">
                            {info.hasError && (
                                <div className="leading-[22px] text-red-600">
                                    {localize("com_tools.knowledge_query_failed")}
                                </div>
                            )}
                            {!info.hasError && info.chunkCount === 0 && (
                                <div className="leading-[22px]">{localize("com_tools.knowledge_no_doc")}</div>
                            )}
                            {info.docs.length > 0 && (
                                <div className={cn("flex flex-wrap gap-2", info.hasError && "mt-2")}>
                                    {docs.map((docTitle) => (
                                        <span
                                            key={docTitle}
                                            className={DOC_CHIP_CLASS}
                                            title={kbLabel ? `${docTitle} · ${kbLabel}` : docTitle}
                                        >
                                            <span className="max-w-[180px] truncate">{docTitle}</span>
                                        </span>
                                    ))}
                                    {hiddenDocCount > 0 && (
                                        <button
                                            type="button"
                                            onClick={() => setShowAllDocs(true)}
                                            className={cn(DOC_CHIP_CLASS, "text-text-3 hover:text-text-1")}
                                        >
                                            {localize("com_tools.knowledge_doc_more", { 0: hiddenDocCount })}
                                        </button>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        );
    },
);

KnowledgeSearchRow.displayName = "KnowledgeSearchRow";

export default KnowledgeSearchRow;
