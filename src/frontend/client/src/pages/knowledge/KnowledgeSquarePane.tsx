import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { KnowledgeSpace } from "~/api/knowledge";
import { useLocalize } from "~/hooks";
import { KnowledgeSpacePreviewDrawer } from "./KnowledgeSpacePreviewDrawer";
import KnowledgeSquare from "./KnowledgeSquare";

type SquareSpaceStatus = "join" | "joined" | "pending" | "rejected";

/**
 * 知识广场 as a self-contained pane — the square list plus the preview drawer a card
 * opens, with the join status the two share — for hosts that are not the 知识空间 page
 * (the unified 广场). The 知识空间 page keeps its own copy of this wiring: there the square
 * is also driven by deep links (`?square=1`, `?previewSpace=`, notification events).
 */
export function KnowledgeSquarePane() {
    const localize = useLocalize();
    const [params, setParams] = useSearchParams();
    const previewSpaceId = params.get("previewSpace") || undefined;
    const [previewSpace, setPreviewSpace] = useState<KnowledgeSpace | null>(null);
    const [statusOverride, setStatusOverride] = useState<Record<string, SquareSpaceStatus>>({});

    const handleStatusChange = (id: string, status: SquareSpaceStatus) => {
        setStatusOverride((prev) => (prev[String(id)] === status ? prev : { ...prev, [String(id)]: status }));
    };

    return (
        <>
            <KnowledgeSquare
                title={localize("com_knowledge.explore_square")}
                subtitle={localize("com_knowledge.explore_more_spaces")}
                searchPlaceholder={localize("com_knowledge.search_space_placeholder")}
                emptyText={localize("com_knowledge.no_matched_space")}
                joinToastPrefix={localize("com_knowledge.applied_to_join_space")}
                onPreviewSpace={(space) => {
                    setPreviewSpace(space);
                    // The host can distinguish a preview from its square entry URL.
                    setParams((current) => {
                        const next = new URLSearchParams(current);
                        next.set("previewSpace", space.id);
                        return next;
                    });
                }}
                statusOverride={statusOverride}
                onSquareStatusChange={handleStatusChange}
            />
            <KnowledgeSpacePreviewDrawer
                spaceId={previewSpaceId}
                initialSpace={
                    previewSpace && previewSpace.id === previewSpaceId
                        ? { ...previewSpace, squareStatus: statusOverride[String(previewSpace.id)] ?? previewSpace.squareStatus }
                        : null
                }
                open={Boolean(previewSpaceId)}
                onOpenChange={(open) => {
                    if (!open) {
                        setPreviewSpace(null);
                        setParams((current) => {
                            const next = new URLSearchParams(current);
                            next.delete("previewSpace");
                            return next;
                        }, { replace: true });
                    }
                }}
                onSquareStatusChange={handleStatusChange}
            />
        </>
    );
}
