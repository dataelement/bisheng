import type {
    ReviewTagSimilarBatchCheckResult,
    ReviewTagSimilarMatchItem,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import { useTranslation } from "react-i18next";

function formatMatchLabel(item: ReviewTagSimilarMatchItem, t: (key: string, defaultValue: string) => string) {
    if (item.match_kind === "substring") {
        return t("build.reviewTagSimilarSubstring", "「{{name}}」（包含关系）", { name: item.name });
    }
    if (item.match_kind === "similarity" && item.score != null) {
        return t("build.reviewTagSimilarScore", "「{{name}}」（相似度 {{score}}%）", {
            name: item.name,
            score: Math.round(item.score * 100),
        });
    }
    return `「${item.name}」`;
}

interface ReviewTagSimilarBatchSummaryProps {
    result: ReviewTagSimilarBatchCheckResult | null;
    loading?: boolean;
}

export function ReviewTagSimilarBatchSummary({ result, loading }: ReviewTagSimilarBatchSummaryProps) {
    const { t } = useTranslation();

    if (loading) {
        return (
            <p className="text-xs text-muted-foreground">
                {t("build.reviewTagSimilarBatchChecking", "正在批量检查目标库中的相似标签…")}
            </p>
        );
    }

    if (!result) {
        return null;
    }

    const similarItems = (result.items ?? []).filter((item) => (item.similar_matches?.length ?? 0) > 0);
    const exactItems = (result.items ?? []).filter((item) => (item.exact_matches?.length ?? 0) > 0);
    if (similarItems.length === 0 && exactItems.length === 0) {
        return null;
    }

    return (
        <div className="space-y-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
            {exactItems.length > 0 && (
                <div>
                    <p className="font-medium">
                        {t("build.reviewTagSimilarBatchExactTitle", "{{count}} 个标签在目标库中已有同名标签", {
                            count: exactItems.length,
                        })}
                    </p>
                    <p className="mt-1 text-xs text-amber-800">
                        {exactItems.map((item) => item.tag_name).join("、")}
                    </p>
                </div>
            )}
            {similarItems.length > 0 && (
                <div>
                    <p className="font-medium">
                        {t("build.reviewTagSimilarBatchTitle", "{{count}} 个标签在目标库中存在相似标签", {
                            count: similarItems.length,
                        })}
                    </p>
                    <ul className="mt-1 list-disc pl-5">
                        {similarItems.map((item) => (
                            <li key={item.tag_name}>
                                <span className="font-medium">{item.tag_name}</span>
                                <span className="ml-1 text-xs text-amber-800">
                                    {item.similar_matches
                                        .map((match) => formatMatchLabel(match, t))
                                        .join("；")}
                                </span>
                            </li>
                        ))}
                    </ul>
                    <p className="mt-1 text-xs text-amber-800">
                        {t("build.reviewTagSimilarMatchHint", "继续通过需二次确认。")}
                    </p>
                </div>
            )}
        </div>
    );
}
