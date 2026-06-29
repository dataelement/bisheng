import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Loader2, Link2, Search } from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent } from "~/components/ui/Tooltip2";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { useLocalize } from "~/hooks";
import { useDebounce } from "~/hooks/Input";
import { useToastContext } from "~/Providers";
import { useConfirm } from "~/Providers";
import {
    getVersionRecommendationsApi,
    searchVersionSourcesApi,
    mergeIntoCurrentApi,
    type SimilarCandidateEntry,
    type SearchableDocumentEntry,
    type LinkAsNewVersionResponse,
} from "~/api/knowledge";
import { type KnowledgeFile } from "~/api/knowledge";
import { cn } from "~/utils";

// ─── Props ─────────────────────────────────────────────────────────────────────

interface RelateDocumentPanelProps {
    spaceId: number;
    fileId: number;
    file: KnowledgeFile;
    onLinked: (response: LinkAsNewVersionResponse) => void;
    className?: string;
}

interface LinkTarget {
    document_id: number;
    title: string;
    force?: boolean;
}

// ─── Recommendation card ───────────────────────────────────────────────────────

interface RecommendationCardProps {
    entry: SimilarCandidateEntry;
    disabled: boolean;
    onLink: (doc: LinkTarget) => void;
}

function RecommendationCard({ entry, disabled, onLink }: RecommendationCardProps) {
    const localize = useLocalize();

    const uploadTimeDisplay = entry.primary_upload_time
        ? entry.primary_upload_time.replace("T", " ").slice(0, 16)
        : null;

    const versionLine = entry.doc_code
        ? `${entry.doc_code} · 当前主版本 V${entry.current_primary_version_no ?? 1}`
        : `当前主版本 V${entry.current_primary_version_no ?? 1}`;

    return (
        <div className="flex items-center justify-between gap-3 rounded-[8px] border border-[#EBECF0] bg-white px-4 py-3 hover:border-[#165DFF] hover:bg-[#F4F8FF] transition-colors group">
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <p className="min-w-0 cursor-default truncate text-[14px] font-medium text-[#1d2129]">
                                {entry.title}
                            </p>
                        </TooltipTrigger>
                        <TooltipContent
                            noArrow
                            side="top"
                            className="max-w-xs rounded-md bg-[#1D2129] px-2 py-1 text-[12px] text-white"
                        >
                            {entry.title}
                        </TooltipContent>
                    </Tooltip>
                    <span className="shrink-0 rounded bg-[#FFF3E8] px-1.5 py-0.5 text-[12px] text-[#F76F44]">
                        {localize("com_knowledge.version.similarity_label")} {((entry.refined_similarity ?? entry.similarity) * 100).toFixed(0)}%
                    </span>
                </div>
                <p className="text-[12px] text-[#86909c] mb-0.5">{versionLine}</p>
                {uploadTimeDisplay && (
                    <p className="text-[12px] text-[#86909c]">{entry.title} · {uploadTimeDisplay}</p>
                )}
            </div>
            <Button
                type="button"
                size="sm"
                disabled={disabled}
                onClick={() =>
                    onLink({ document_id: entry.target_document_id, title: entry.title })
                }
                className="h-8 shrink-0 rounded-[6px] bg-[#165DFF] px-4 text-[12px] text-white hover:bg-[#4080FF]"
            >
                <Link2 className="mr-1.5 size-4" />
                {localize("com_knowledge.version.btn_link_as_new_version")}
            </Button>
        </div>
    );
}

// ─── Search result row ─────────────────────────────────────────────────────────

interface SearchResultRowProps {
    entry: SearchableDocumentEntry;
    disabled: boolean;
    onLink: (doc: LinkTarget) => void;
}

function SearchResultRow({ entry, disabled, onLink }: SearchResultRowProps) {
    const localize = useLocalize();
    return (
        <div className="flex items-center justify-between gap-3 border-b border-[#F2F3F5] px-3 py-2.5 last:border-b-0 hover:bg-[#FAFAFA]">
            <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-[#1d2129]">{entry.title}</p>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-[#86909c]">
                    <span>V{entry.current_primary_version_no ?? 1}</span>
                    {entry.doc_code && <span>{entry.doc_code}</span>}
                    {entry.primary_uploader_name && <span>{entry.primary_uploader_name}</span>}
                </div>
            </div>
            <Button
                type="button"
                size="sm"
                disabled={disabled}
                onClick={() => onLink({ document_id: entry.document_id, title: entry.title, force: true })}
                className="h-8 shrink-0 rounded-[6px] bg-[#165DFF] px-4 text-[12px] text-white hover:bg-[#4080FF]"
            >
                <Link2 className="mr-1.5 size-4" />
                {localize("com_knowledge.version.btn_link_as_new_version")}
            </Button>
        </div>
    );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export function RelateDocumentPanel({
    spaceId,
    fileId,
    file,
    onLinked,
    className,
}: RelateDocumentPanelProps): JSX.Element {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const [keyword, setKeyword] = useState("");
    const debouncedKeyword = useDebounce(keyword, 300);

    // Fetch single-version similarity recommendations (merge-source eligible)
    const { data: candidates = [], isLoading: candidatesLoading } = useQuery({
        queryKey: ["version-recommendations", fileId],
        queryFn: () => getVersionRecommendationsApi(fileId),
        enabled: fileId > 0,
    });

    // Fetch search results when debounced keyword is at least 1 char
    const { data: searchResults = [], isLoading: searchLoading } = useQuery({
        queryKey: ["version-source-search", spaceId, debouncedKeyword, fileId],
        queryFn: () => searchVersionSourcesApi(spaceId, debouncedKeyword, fileId),
        enabled: debouncedKeyword.length >= 1,
    });

    const linkMutation = useMutation({
        mutationFn: (target: { source_document_id: number; force?: boolean }) =>
            mergeIntoCurrentApi({
                current_knowledge_file_id: fileId,
                source_document_id: target.source_document_id,
                force: target.force,
            }),
        onSuccess: (response) => {
            showToast({
                message: localize("com_knowledge.version.toast_link_success"),
                status: "success",
            });
            onLinked(response);
        },
        // The unified request interceptor already toasts api_errors.<code>
        // (e.g. 18061/18062/18063/18064) when skip403Redirect is set, so the
        // onError handler is a no-op to avoid a duplicate generic toast that
        // would overwrite the precise product-spec message.
        onError: () => undefined,
    });

    const handleLink = async (targetDoc: LinkTarget) => {
        const ok = await confirm({
            title: localize("com_knowledge.version.confirm_link_title"),
            description: localize("com_knowledge.version.confirm_merge_description", {
                name: file.name,
                target: targetDoc.title,
            }),
        });
        if (ok) {
            linkMutation.mutate({
                source_document_id: targetDoc.document_id,
                force: targetDoc.force,
            });
        }
    };

    const isLinking = linkMutation.isPending;
    const hasSearched = debouncedKeyword.length >= 1;

    return (
        <div className={cn("flex flex-col gap-5 h-full", className)}>
            {/* ── Section 1: Current file ─────────────────────────────── */}
            <section className="rounded-[8px] border border-[#EBECF0] bg-[#FAFAFA] px-4 py-3 flex items-start justify-between shrink-0">
                <div className="flex-1 min-w-0 pr-4">
                    <p className="text-[12px] text-[#86909c] mb-1">
                        {localize("com_knowledge.version.section_current_file")}
                    </p>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <p className="truncate text-[16px] font-medium text-[#1d2129] mb-1">
                                {file.name}
                            </p>
                        </TooltipTrigger>
                        <TooltipContent
                            noArrow
                            side="top"
                            className="max-w-xs rounded-md bg-[#1D2129] px-2 py-1 text-[12px] text-white"
                        >
                            {file.name}
                        </TooltipContent>
                    </Tooltip>
                    <p className="text-[12px] text-[#86909c]">
                        当前主版本 V{file.version_no ?? 1} · 上传人 {file.user_name ?? "未知"}
                    </p>
                </div>
                <span className="shrink-0 rounded bg-[#FFF3E8] px-2 py-0.5 text-[12px] text-[#F76F44] font-medium mt-1">
                    {localize("com_knowledge.version.current_file_recommend_pill", {
                        count: candidates.length,
                    })}
                </span>
            </section>

            {/* ── Sections 2 & 3: Recommendations and Search ──────────── */}
            <div className="shrink-0 flex flex-col rounded-[8px] border border-[#EBECF0] bg-white">
                {/* ── Section 2: Recommendations ──────────────────────────── */}
                <section className="p-4 border-b border-[#EBECF0]">
                    <h3 className="mb-0.5 text-[14px] font-medium text-[#1d2129]">
                        {localize("com_knowledge.version.section_recommendations")}
                    </h3>
                    <p className="mb-3 text-[12px] text-[#86909c]">
                        {localize("com_knowledge.version.section_recommendations_subtitle_merge")}
                    </p>
                    {candidatesLoading ? (
                        <div className="flex h-16 items-center justify-center border border-[#EBECF0] bg-[#FAFAFA] rounded-[6px]">
                            <Loader2 className="size-5 animate-spin text-[#86909c]" />
                        </div>
                    ) : candidates.length === 0 ? (
                        <div className="flex h-[72px] items-center justify-center border border-[#EBECF0] bg-[#FAFAFA] rounded-[6px]">
                            <p className="text-[14px] text-[#86909c]">
                                {localize("com_knowledge.version.no_recommendations")}
                            </p>
                        </div>
                    ) : (
                        <div className="flex flex-col gap-2 max-h-[220px] overflow-y-auto scrollbar-on-scroll border border-[#EBECF0] bg-[#FAFAFA] rounded-[6px] p-2">
                            {candidates.map((entry) => (
                                <RecommendationCard
                                    key={entry.target_document_id}
                                    entry={entry}
                                    disabled={isLinking}
                                    onLink={handleLink}
                                />
                            ))}
                        </div>
                    )}
                </section>

                {/* ── Section 3: Search existing documents ────────────────── */}
                <section className="p-4">
                    <h3 className="mb-0.5 text-[14px] font-medium text-[#1d2129]">
                        {localize("com_knowledge.version.section_search")}
                    </h3>
                    <p className="mb-3 text-[12px] text-[#86909c]">
                        {localize("com_knowledge.version.section_search_subtitle")}
                    </p>
                    {/* Search input + button row */}
                    <div className="mb-3 flex gap-2">
                        <Input
                            type="text"
                            value={keyword}
                            onChange={(e) => setKeyword(e.target.value)}
                            placeholder={localize("com_knowledge.version.search_placeholder")}
                            className="h-8 flex-1 rounded-[6px] border-[#EBECF0] text-[12px] bg-white"
                        />
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            className="h-8 rounded-[6px] px-4 text-[12px] text-[#4e5969] bg-white border-[#EBECF0]"
                        >
                            <Search className="mr-1.5 size-4" />
                            {localize("com_knowledge.version.search_button")}
                        </Button>
                    </div>

                    {/* Search results or placeholder */}
                    {!hasSearched ? (
                        // Centered placeholder hint when no keyword has been entered
                        <div className="flex h-16 items-center justify-center rounded-[6px] border border-dashed border-[#EBECF0] bg-[#FAFAFA]">
                            <p className="text-[14px] text-[#c9cdd4]">
                                {localize("com_knowledge.version.search_placeholder")}
                            </p>
                        </div>
                    ) : (
                        <div className="rounded-[6px] border border-[#EBECF0] bg-white">
                            {searchLoading ? (
                                <div className="flex h-16 items-center justify-center">
                                    <Loader2 className="size-5 animate-spin text-[#86909c]" />
                                </div>
                            ) : searchResults.length === 0 ? (
                                <p className="px-3 py-4 text-[14px] text-[#86909c]">
                                    {localize("com_knowledge.version.no_search_results")}
                                </p>
                            ) : (
                                <div className="max-h-[220px] overflow-y-auto scrollbar-on-scroll">
                                    {searchResults.map((entry) => (
                                        <SearchResultRow
                                            key={entry.document_id}
                                            entry={entry}
                                            disabled={isLinking}
                                            onLink={handleLink}
                                        />
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </section>
            </div>
        </div>
    );
}
