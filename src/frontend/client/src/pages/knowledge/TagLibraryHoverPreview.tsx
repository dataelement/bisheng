import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
    extractTagLibraryPreviewNames,
    getKnowledgeSpaceTagLibraryDetailApi,
} from "~/api/knowledge";
import { useLocalize } from "~/hooks";

export const TAG_LIBRARY_DETAIL_STALE_TIME = 60_000;

export function tagLibraryDetailQueryKey(libraryId: number) {
    return ["knowledgeSpaces", "tagLibraryDetail", libraryId] as const;
}

interface TagLibraryHoverPreviewProps {
    libraryId: number;
    libraryName: string;
}

export function TagLibraryHoverPreview({
    libraryId,
    libraryName,
}: TagLibraryHoverPreviewProps) {
    const localize = useLocalize();
    const { data, isLoading, isError } = useQuery({
        queryKey: tagLibraryDetailQueryKey(libraryId),
        queryFn: () => getKnowledgeSpaceTagLibraryDetailApi(libraryId),
        staleTime: TAG_LIBRARY_DETAIL_STALE_TIME,
        retry: false,
    });
    const tags = useMemo(
        () => data ? extractTagLibraryPreviewNames(data) : [],
        [data],
    );

    return (
        <div data-testid={`tag-library-hover-preview-${libraryId}`} className="min-w-0">
            <div className="mb-2 text-[14px] font-medium text-[#1D2129]">
                {libraryName}
                {!isLoading && !isError ? ` (${tags.length})` : ""}
            </div>
            {isLoading ? (
                <div role="status" className="text-[12px] text-[#86909C]">
                    {localize("com_knowledge.loading")}
                </div>
            ) : isError ? (
                <div role="alert" className="text-[12px] text-[#F53F3F]">
                    {localize("com_knowledge.load_tag_libraries_failed")}
                </div>
            ) : tags.length === 0 ? (
                <div className="text-[12px] text-[#86909C]">
                    {localize("com_knowledge.auto_tag_library_preview_empty")}
                </div>
            ) : (
                <div className="flex flex-wrap items-center">
                    {tags.map((tag, index) => (
                        <span
                            key={`${tag}-${index}`}
                            className="mb-1.5 mr-1.5 inline-flex max-w-full break-all rounded-full bg-[#E8F3FF] px-2 py-0.5 text-[12px] text-[#165DFF]"
                        >
                            {tag}
                        </span>
                    ))}
                </div>
            )}
        </div>
    );
}
