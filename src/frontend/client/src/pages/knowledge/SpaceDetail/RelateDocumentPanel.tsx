import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Loader2, Link2 } from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent } from "~/components/ui/Tooltip2";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { useLocalize } from "~/hooks";
import { useDebounce } from "~/hooks/Input";
import { useToastContext } from "~/Providers";
import { useConfirm } from "~/Providers";
import {
    getSimilarCandidatesApi,
    searchDocumentsApi,
    linkAsNewVersionApi,
    type SimilarCandidateEntry,
    type SearchableDocumentEntry,
    type LinkAsNewVersionResponse,
} from "~/api/knowledge";
import { cn } from "~/utils";

// ─── Props ─────────────────────────────────────────────────────────────────────

interface RelateDocumentPanelProps {
    spaceId: number;
    fileId: number;
    fileName: string;
    onLinked: (response: LinkAsNewVersionResponse) => void;
    className?: string;
}

// ─── Recommendation card ───────────────────────────────────────────────────────

interface RecommendationCardProps {
    entry: SimilarCandidateEntry;
    disabled: boolean;
    onLink: (doc: { document_id: number; title: string }) => void;
}

function RecommendationCard({ entry, disabled, onLink }: RecommendationCardProps) {
    const localize = useLocalize();
    return (
        <div className="flex items-center justify-between gap-3 rounded-[6px] border border-[#EBECF0] bg-white px-3 py-2.5">
            <div className="min-w-0 flex-1">
                <Tooltip>
                    <TooltipTrigger asChild>
                        <p className="cursor-default truncate text-sm font-medium text-[#1d2129]">
                            {entry.title}
                        </p>
                    </TooltipTrigger>
                    <TooltipContent
                        noArrow
                        side="top"
                        className="max-w-xs rounded-md bg-[#1D2129] px-2 py-1 text-xs text-white"
                    >
                        {entry.title}
                    </TooltipContent>
                </Tooltip>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-[#86909c]">
                    {entry.doc_code && (
                        <span>{entry.doc_code}</span>
                    )}
                    <span>
                        {localize("com_knowledge.version.similarity_label")}
                        {": "}
                        {(entry.similarity * 100).toFixed(1)}%
                    </span>
                </div>
            </div>
            <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled}
                onClick={() =>
                    onLink({ document_id: entry.target_document_id, title: entry.title })
                }
                className="h-7 shrink-0 rounded-[6px] px-3 text-xs"
            >
                <Link2 className="mr-1.5 size-3" />
                {localize("com_knowledge.version.btn_link_as_new_version")}
            </Button>
        </div>
    );
}

// ─── Search result row ─────────────────────────────────────────────────────────

interface SearchResultRowProps {
    entry: SearchableDocumentEntry;
    disabled: boolean;
    onLink: (doc: { document_id: number; title: string }) => void;
}

function SearchResultRow({ entry, disabled, onLink }: SearchResultRowProps) {
    const localize = useLocalize();
    return (
        <div className="flex items-center justify-between gap-3 border-b border-[#F2F3F5] px-3 py-2.5 last:border-b-0 hover:bg-[#FAFAFA]">
            <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-[#1d2129]">{entry.title}</p>
                {entry.file_level_path && (
                    <p className="truncate text-xs text-[#86909c]">{entry.file_level_path}</p>
                )}
            </div>
            <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={disabled}
                onClick={() => onLink({ document_id: entry.document_id, title: entry.title })}
                className="h-7 shrink-0 rounded-[6px] px-3 text-xs"
            >
                <Link2 className="mr-1.5 size-3" />
                {localize("com_knowledge.version.btn_link_as_new_version")}
            </Button>
        </div>
    );
}

// ─── Main panel ───────────────────────────────────────────────────────────────

export function RelateDocumentPanel({
    spaceId,
    fileId,
    fileName,
    onLinked,
    className,
}: RelateDocumentPanelProps): JSX.Element {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const confirm = useConfirm();
    const [keyword, setKeyword] = useState("");
    const debouncedKeyword = useDebounce(keyword, 300);

    // Fetch similarity recommendations
    const { data: candidates = [], isLoading: candidatesLoading } = useQuery({
        queryKey: ["similar-candidates", fileId],
        queryFn: () => getSimilarCandidatesApi(fileId),
        enabled: fileId > 0,
    });

    // Fetch search results when debounced keyword is at least 1 char
    const { data: searchResults = [], isLoading: searchLoading } = useQuery({
        queryKey: ["document-search", spaceId, debouncedKeyword],
        queryFn: () => searchDocumentsApi(spaceId, debouncedKeyword),
        enabled: debouncedKeyword.length >= 1,
    });

    const linkMutation = useMutation({
        mutationFn: (target_document_id: number) =>
            linkAsNewVersionApi({ knowledge_file_id: fileId, target_document_id }),
        onSuccess: (response) => {
            showToast({
                message: localize("com_knowledge.version.toast_link_success"),
                status: "success",
            });
            onLinked(response);
        },
        onError: () => {
            showToast({
                message: localize("com_knowledge.version.toast_link_failure"),
                status: "error",
            });
        },
    });

    const handleLink = async (targetDoc: { document_id: number; title: string }) => {
        const ok = await confirm({
            title: localize("com_knowledge.version.confirm_link_title"),
            description: localize("com_knowledge.version.confirm_link_description", {
                name: fileName,
                target: targetDoc.title,
            }),
        });
        if (ok) {
            linkMutation.mutate(targetDoc.document_id);
        }
    };

    const isLinking = linkMutation.isPending;
    const hasSearched = debouncedKeyword.length >= 1;

    return (
        <div className={cn("flex flex-col gap-5", className)}>
            {/* Recommendation section */}
            <section>
                <h3 className="mb-2.5 text-sm font-medium text-[#1d2129]">
                    {localize("com_knowledge.version.section_recommendations")}
                </h3>
                {candidatesLoading ? (
                    <div className="flex h-16 items-center justify-center">
                        <Loader2 className="size-5 animate-spin text-[#86909c]" />
                    </div>
                ) : candidates.length === 0 ? (
                    <p className="text-sm text-[#86909c]">
                        {localize("com_knowledge.version.no_recommendations")}
                    </p>
                ) : (
                    <div className="flex flex-col gap-2">
                        {candidates.map((entry) => (
                            <RecommendationCard
                                key={entry.document_id}
                                entry={entry}
                                disabled={isLinking}
                                onLink={handleLink}
                            />
                        ))}
                    </div>
                )}
            </section>

            {/* Divider */}
            <div className="h-px bg-[#EBECF0]" />

            {/* Search section */}
            <section>
                <h3 className="mb-2.5 text-sm font-medium text-[#1d2129]">
                    {localize("com_knowledge.version.section_search")}
                </h3>
                <Input
                    type="text"
                    value={keyword}
                    onChange={(e) => setKeyword(e.target.value)}
                    placeholder={localize("com_knowledge.version.search_placeholder")}
                    className="mb-3 h-8 rounded-[6px] border-[#EBECF0] text-sm"
                />

                {hasSearched && (
                    <div className="rounded-[6px] border border-[#EBECF0] bg-white">
                        {searchLoading ? (
                            <div className="flex h-16 items-center justify-center">
                                <Loader2 className="size-5 animate-spin text-[#86909c]" />
                            </div>
                        ) : searchResults.length === 0 ? (
                            <p className="px-3 py-4 text-sm text-[#86909c]">
                                {localize("com_knowledge.version.no_search_results")}
                            </p>
                        ) : (
                            <div className="max-h-[280px] overflow-y-auto">
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
    );
}
