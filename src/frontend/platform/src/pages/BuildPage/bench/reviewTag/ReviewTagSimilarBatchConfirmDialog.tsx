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
import type { ReviewTagSimilarBatchItem, ReviewTagSimilarMatchItem } from "@/controllers/API/knowledgeSpaceTagLibrary";
import { useTranslation } from "react-i18next";

interface ReviewTagSimilarBatchConfirmDialogProps {
    open: boolean;
    items: ReviewTagSimilarBatchItem[];
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

export function ReviewTagSimilarBatchConfirmDialog({
    open,
    items,
    saving = false,
    onOpenChange,
    onConfirm,
}: ReviewTagSimilarBatchConfirmDialogProps) {
    const { t } = useTranslation();

    return (
        <AlertDialog open={open} onOpenChange={onOpenChange}>
            <AlertDialogContent className="sm:max-w-[560px]">
                <AlertDialogHeader>
                    <AlertDialogTitle>{t("build.reviewTagSimilarConfirmTitle", "确认仍要通过？")}</AlertDialogTitle>
                    <AlertDialogDescription className="space-y-3 text-left">
                        <span className="block">
                            {t(
                                "build.reviewTagSimilarBatchConfirmDesc",
                                "以下 {{count}} 个标签与目标库中已有标签相似，继续批量入库可能产生重复词条。",
                                { count: items.length },
                            )}
                        </span>
                        <div className="max-h-60 overflow-y-auto rounded-md border border-[#ECECEC] bg-[#FAFBFC] p-3">
                            {items.map((item) => (
                                <div key={item.tag_name} className="py-1 text-sm">
                                    <p className="font-medium">{item.tag_name}</p>
                                    <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                                        {item.similar_matches.map((match) => (
                                            <li key={`${item.tag_name}-${match.name}-${match.match_kind}`}>
                                                {formatMatchLabel(match, t)}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            ))}
                        </div>
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
