import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/bs-ui/alertDialog";
import type { ReviewTagSimilarMatchItem } from "@/controllers/API/knowledgeSpaceTagLibrary";
import { useTranslation } from "react-i18next";

interface ReviewTagSimilarConfirmDialogProps {
    open: boolean;
    tagName: string;
    similarMatches: ReviewTagSimilarMatchItem[];
    saving?: boolean;
    onOpenChange: (open: boolean) => void;
    onConfirm: () => void;
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

export function ReviewTagSimilarConfirmDialog({
    open,
    tagName,
    similarMatches,
    saving = false,
    onOpenChange,
    onConfirm,
}: ReviewTagSimilarConfirmDialogProps) {
    const { t } = useTranslation();

    return (
        <AlertDialog open={open} onOpenChange={onOpenChange}>
            <AlertDialogContent className="sm:max-w-[480px]">
                <AlertDialogHeader>
                    <AlertDialogTitle>{t("build.reviewTagSimilarConfirmTitle", "确认仍要通过？")}</AlertDialogTitle>
                    <AlertDialogDescription className="space-y-2 text-left">
                        <span className="block">
                            {t(
                                "build.reviewTagSimilarConfirmDesc",
                                "标签「{{tagName}}」与目标库中以下标签相似，继续通过可能产生重复词条。",
                                { tagName },
                            )}
                        </span>
                        <ul className="list-disc pl-5 text-left text-sm text-foreground">
                            {similarMatches.map((item) => (
                                <li key={`confirm-${item.name}-${item.match_kind}`}>{formatMatchLabel(item, t)}</li>
                            ))}
                        </ul>
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogCancel disabled={saving}>{t("cancel", { ns: "bs" })}</AlertDialogCancel>
                    <AlertDialogAction disabled={saving} onClick={onConfirm}>
                        {t("build.reviewTagSimilarConfirmAction", "仍要通过")}
                    </AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    );
}
