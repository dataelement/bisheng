import type { ComponentProps, ReactNode } from "react";
import { Button } from "~/components/ui/Button";
import { LoadingIcon } from "~/components/ui/icon/Loading";
import useLocalize from "~/hooks/useLocalize";
import { cn } from "~/utils";
import { SectionHeader } from "./SectionHeader";

interface KnowledgeSpaceSectionProps extends ComponentProps<typeof SectionHeader> {
    children: ReactNode[];
    stretch?: boolean;
    loading?: boolean;
    onRetry?: () => void;
}

export function KnowledgeSpaceSection({
    children,
    stretch,
    loading,
    onRetry,
    ...header
}: KnowledgeSpaceSectionProps) {
    const localize = useLocalize();
    const fill = stretch && !header.collapsed;
    const rowClass = header.mobile ? "w-[100cqi] px-4 py-2"
        : header.compact ? "space-y-1 px-3" : "space-y-0.5 px-3";

    return (
        <div className={cn("pb-4", fill && "flex flex-1 flex-col")}>
            <SectionHeader {...header} />
            {!header.collapsed && (
                <div className={cn(rowClass, fill && "flex flex-1 flex-col")}>
                    {!loading && !onRetry && children.length > 0 ? children : (
                        <div className={cn(
                            "flex flex-col items-center justify-center gap-2 text-center text-body-sm text-text-3",
                            !header.mobile && "sticky left-0 -mx-3 w-[100cqi]",
                            fill ? "flex-1 py-6" : header.compact ? "py-6" : "h-24",
                        )}>
                            {loading ? (
                                <div role="status" className="flex flex-col items-center gap-2">
                                    <LoadingIcon className="size-10" />
                                    <span>{localize("com_list_loading")}</span>
                                </div>
                            ) : onRetry ? (
                                <>
                                    <span>{localize("com_list_load_failed")}</span>
                                    <Button color="default" variant="text" size="small" onClick={onRetry}>
                                        {localize("com_error_retry")}
                                    </Button>
                                </>
                            ) : localize("com_knowledge.no_data")}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
