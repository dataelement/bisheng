import { checkReviewTagSimilarApi, type ReviewTagSimilarCheckResult } from "@/controllers/API/knowledgeSpaceTagLibrary";
import { useEffect, useState } from "react";

export function useReviewTagSimilarCheck(tagName: string | undefined, libraryId: string) {
    const [result, setResult] = useState<ReviewTagSimilarCheckResult | null>(null);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        const normalizedName = tagName?.trim();
        const normalizedLibraryId = libraryId.trim();
        if (!normalizedName || !normalizedLibraryId) {
            setResult(null);
            setLoading(false);
            return;
        }

        let cancelled = false;
        const timer = window.setTimeout(() => {
            setLoading(true);
            void checkReviewTagSimilarApi({
                tag_name: normalizedName,
                tag_library_id: Number(normalizedLibraryId),
            })
                .then((res) => {
                    if (!cancelled) {
                        setResult(res);
                    }
                })
                .catch(() => {
                    if (!cancelled) {
                        setResult(null);
                    }
                })
                .finally(() => {
                    if (!cancelled) {
                        setLoading(false);
                    }
                });
        }, 300);

        return () => {
            cancelled = true;
            window.clearTimeout(timer);
        };
    }, [tagName, libraryId]);

    const hasSimilar = (result?.similar_matches?.length ?? 0) > 0;
    const hasExact = (result?.exact_matches?.length ?? 0) > 0;

    return { result, loading, hasSimilar, hasExact };
}
