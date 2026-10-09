import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useLocalize } from "~/hooks";

interface PortalFilePaginationProps {
    currentPage: number;
    maxVisitedPage: number;
    hasMore: boolean;
    loading: boolean;
    total?: number;
    terminalKnown?: boolean;
    onPageChange: (page: number) => void;
}

export function PortalFilePagination({ currentPage, maxVisitedPage, hasMore, loading, total, terminalKnown = true, onPageChange }: PortalFilePaginationProps) {
    const localize = useLocalize();
    const [draftPage, setDraftPage] = useState(String(currentPage));
    useEffect(() => setDraftPage(String(currentPage)), [currentPage]);
    const pages = maxVisitedPage <= 5 ? Array.from({ length: maxVisitedPage }, (_, index) => index + 1) : [...new Set([1, currentPage - 1, currentPage, currentPage + 1, maxVisitedPage])]
        .filter(page => page >= 1 && page <= maxVisitedPage).sort((a, b) => a - b);
    const handleSubmit = (event: React.FormEvent) => {
        event.preventDefault();
        const page = Number(draftPage);
        if (!loading && Number.isInteger(page) && page >= 1 && page <= maxVisitedPage) onPageChange(page);
        else setDraftPage(String(currentPage));
    };
    const nextAvailable = currentPage < maxVisitedPage || hasMore;
    if (loading && maxVisitedPage === 0) return null;
    return (
        <nav aria-label={localize("com_knowledge.history_pagination")} className="flex w-full min-w-0 flex-wrap items-center justify-end gap-2 text-xs text-gray-600" data-testid="portal-file-pagination">
            <span role="status" aria-live="polite">
                {maxVisitedPage > 0 ? localize("com_knowledge.history_page", { page: currentPage, visited: maxVisitedPage }) : localize(loading ? "com_knowledge.loading" : "com_knowledge.history_empty")}
                {terminalKnown && !loading && maxVisitedPage > 0 && !hasMore && currentPage === maxVisitedPage && ` · ${localize("com_knowledge.history_end")}`}
                {total !== undefined && ` · ${localize("com_knowledge.history_matches", { count: total })}`}
            </span>
            <button type="button" disabled={loading || currentPage <= 1} onClick={() => onPageChange(currentPage - 1)} aria-label={localize("com_knowledge.history_previous")} className="rounded border p-1.5 disabled:opacity-40">
                <ChevronLeft size={16} />
            </button>
            {pages.map((page, index) => (
                <span key={page} className="flex items-center gap-2">
                    {index > 0 && page - pages[index - 1] > 1 && <span aria-hidden="true">…</span>}
                    <button type="button" aria-label={localize("com_knowledge.history_go_page", { page })} aria-current={page === currentPage ? "page" : undefined} disabled={loading}
                        onClick={() => onPageChange(page)} className={`min-w-7 rounded border px-2 py-1.5 disabled:opacity-40 ${page === currentPage ? "border-blue-600 bg-blue-50 text-blue-600" : ""}`}>
                        {page}
                    </button>
                </span>
            ))}
            <button type="button" disabled={loading || !nextAvailable} onClick={() => onPageChange(currentPage + 1)} aria-label={localize("com_knowledge.history_next")} className="rounded border p-1.5 disabled:opacity-40">
                <ChevronRight size={16} />
            </button>
            {maxVisitedPage > 5 && (
                <form onSubmit={handleSubmit} className="flex items-center gap-1">
                    <input type="number" min={1} max={maxVisitedPage} value={draftPage} disabled={loading} aria-label={localize("com_knowledge.history_page_input")}
                        onChange={event => setDraftPage(event.target.value)} className="w-14 rounded border px-1 py-1.5" />
                    <button type="submit" disabled={loading} className="rounded border px-2 py-1.5">{localize("com_knowledge.history_go")}</button>
                </form>
            )}
        </nav>
    );
}
