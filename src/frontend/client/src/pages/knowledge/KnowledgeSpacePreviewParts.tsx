import type { KnowledgeSpace } from "~/api/knowledge";
import { EmptyStateIllustration, SystemMaintenanceIllustration } from "~/components/illustrations";
import { Button } from "~/components/ui/Button";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import { SheetHeader, SheetTitle } from "~/components/ui/Sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";

interface PreviewSpaceHeaderProps {
    space: KnowledgeSpace;
    status: "none" | "joined" | "pending" | "rejected";
    action: { label: string; variant: "secondary" | "outline" | "default"; disabled: boolean };
    onAction: () => void;
}

export function PreviewSpaceHeader({ space, status, action, onAction }: PreviewSpaceHeaderProps) {
    const localize = useLocalize();

    return (
        <SheetHeader className="gap-0 border-b border-gray-100 px-6 pb-4 pt-6 text-left touch-mobile:px-0 touch-mobile:pt-6">
            <SheetTitle className="mb-1 text-text-1 leading-tight font-semibold touch-mobile:pr-10">
                {space.name}
            </SheetTitle>
            {space.description && (
                <Tooltip>
                    <TooltipTrigger asChild>
                        <p className="text-sm text-text-3 leading-relaxed line-clamp-2 cursor-default text-left">
                            {space.description}
                        </p>
                    </TooltipTrigger>
                    <TooltipContent className="shadow-lg py-2 max-w-md text-sm">
                        {space.description}
                    </TooltipContent>
                </Tooltip>
            )}

            <div className="flex items-center gap-1.5 mb-3 mt-4">
                <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-xs">
                    {space.creator?.[0] || "?"}
                </span>
                <span className="text-sm text-text-3">{space.creator}</span>
            </div>

            <div className="flex items-center justify-between">
                <div className="flex items-center text-sm text-text-3">
                    <span className="mr-3">
                        {localize("com_knowledge.square_preview_parsed_total", { total: space.fileCount ?? 0 })}
                    </span>
                    <span>{space.memberCount ?? 0} {localize("com_knowledge.users_count")}</span>
                </div>
                <Button
                    variant={action.variant}
                    className={`h-8 px-5 py-1 text-sm font-normal rounded-md flex-shrink-0 ${status === "joined"
                        ? "bg-fill-2 text-text-3 border-border-base"
                        : status === "pending"
                            ? "bg-fill-2 text-text-4 border-border-base"
                            : ""
                        }`}
                    disabled={action.disabled}
                    onClick={onAction}
                >
                    {action.label}
                </Button>
            </div>
        </SheetHeader>
    );
}

interface PreviewFolderListStateProps {
    state: "loading" | "ready" | "error";
    hasParsedContent: boolean;
    onRetry: () => void;
}

export function PreviewFolderListState({ state, hasParsedContent, onRetry }: PreviewFolderListStateProps) {
    const localize = useLocalize();

    if (state === "loading") return (
        <div className="flex flex-1 items-center justify-center" role="status" aria-label={localize("com_list_loading")}>
            <LoadingIcon className="size-20 text-primary" />
        </div>
    );

    return (
        <div className="flex flex-1 flex-col items-center justify-center gap-4 p-4 text-center">
            {state === "error" ? (
                <>
                    <SystemMaintenanceIllustration className="size-[120px]" />
                    <p className="text-body text-text-3">{localize("com_knowledge.load_file_list_failed")}</p>
                    <Button color="default" variant="outlined" onClick={onRetry}>{localize("com_error_retry")}</Button>
                </>
            ) : (
                <>
                    <EmptyStateIllustration className="size-[120px]" />
                    <p className="text-body text-text-3">{localize("com_knowledge.square_preview_empty_directory")}</p>
                    {hasParsedContent ? (
                        <p className="max-w-[400px] text-body-sm text-text-3">{localize("com_knowledge.square_preview_total_scope")}</p>
                    ) : null}
                </>
            )}
        </div>
    );
}
