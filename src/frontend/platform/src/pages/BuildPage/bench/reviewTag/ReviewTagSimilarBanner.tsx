import type { ReviewTagSimilarCheckResult, ReviewTagSimilarMatchItem } from "@/controllers/API/knowledgeSpaceTagLibrary";
import { useTranslation } from "react-i18next";

interface ReviewTagSimilarBannerProps {
    result: ReviewTagSimilarCheckResult | null;
    loading?: boolean;
}

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

export function ReviewTagSimilarBanner({ result, loading }: ReviewTagSimilarBannerProps) {
    const { t } = useTranslation();

    if (loading) {
        return (
            <p className="text-xs text-muted-foreground">
                {t("build.reviewTagSimilarChecking", "正在检查目标库中的相似标签…")}
            </p>
        );
    }

    if (!result) {
        return null;
    }

    const exactItems = result.exact_matches ?? [];
    const similarItems = result.similar_matches ?? [];
    if (exactItems.length === 0 && similarItems.length === 0) {
        return null;
    }

    return (
        <div className="space-y-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
            {exactItems.length > 0 && (
                <div>
                    <p className="font-medium">{t("build.reviewTagExactMatchTitle", "目标库已存在同名标签")}</p>
                    <ul className="mt-1 list-disc pl-5">
                        {exactItems.map((item) => (
                            <li key={`exact-${item.name}`}>{formatMatchLabel(item, t)}</li>
                        ))}
                    </ul>
                    <p className="mt-1 text-xs text-amber-800">
                        {t("build.reviewTagExactMatchHint", "审核通过后将直接复用现有标签。")}
                    </p>
                </div>
            )}
            {similarItems.length > 0 && (
                <div>
                    <p className="font-medium">{t("build.reviewTagSimilarMatchTitle", "目标库存在相似标签")}</p>
                    <ul className="mt-1 list-disc pl-5">
                        {similarItems.map((item) => (
                            <li key={`similar-${item.name}-${item.match_kind}`}>{formatMatchLabel(item, t)}</li>
                        ))}
                    </ul>
                    <p className="mt-1 text-xs text-amber-800">
                        {t("build.reviewTagSimilarMatchHint", "继续通过需二次确认。")}
                        {result.similarity_threshold != null && (
                            <span className="ml-1">
                                {t("build.reviewTagSimilarThresholdApplied", "（当前阈值 {{threshold}}）", {
                                    threshold: result.similarity_threshold,
                                })}
                            </span>
                        )}
                    </p>
                </div>
            )}
        </div>
    );
}
