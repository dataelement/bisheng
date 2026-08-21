import {
    checkReviewTagSimilarBatchApi,
    type ReviewTagSimilarBatchCheckResult,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import { useEffect, useMemo, useState } from "react";

export function useReviewTagSimilarBatchCheck(tagNames: string[], libraryId: string) {
    const [result, setResult] = useState<ReviewTagSimilarBatchCheckResult | null>(null);
    const [loading, setLoading] = useState(false);

    const normalizedTagNames = useMemo(
        () => Array.from(new Set(tagNames.map((name) => name.trim()).filter(Boolean))),
        [tagNames],
    );

    useEffect(() => {
        const normalizedLibraryId = libraryId.trim();
        if (!normalizedTagNames.length || !normalizedLibraryId) {
            setResult(null);
            setLoading(false);
            return;
        }

        let cancelled = false;
        const timer = window.setTimeout(() => {
            setLoading(true);
            void checkReviewTagSimilarBatchApi({
                tag_names: normalizedTagNames,
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
    }, [normalizedTagNames, libraryId]);

    const similarItems = useMemo(
        () => (result?.items ?? []).filter((item) => (item.similar_matches?.length ?? 0) > 0),
        [result],
    );
    const hasSimilar = similarItems.length > 0;

    return { result, loading, hasSimilar, similarItems };
}
