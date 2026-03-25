import React from "react";
import { useSelectionPath } from "./useSelectionPath";
import { useLocalize } from "~/hooks";

interface SelectionPathBreadcrumbProps {
    spaceId: string;
    spaceName: string;
    selectedFiles: Set<string>;
    displayFiles: Array<{ id: string; name: string }>;
}

/**
 * Shows the common ancestor path of selected files during search mode.
 * Extracted from SpaceDetail/index.tsx.
 */
export function SelectionPathBreadcrumb({
    spaceId,
    spaceName,
    selectedFiles,
    displayFiles,
}: SelectionPathBreadcrumbProps) {
    const localize = useLocalize();
  const { commonPath, isLoading } = useSelectionPath(spaceId, spaceName, selectedFiles, displayFiles);

    if (isLoading) {
        return <span className="text-xs text-[#86909c]">{localize("com_knowledge.loading_path")}</span>;
    }

    if (commonPath.length === 0) {
        return null;
    }

    return (
        <div className="flex items-center gap-0.5 text-sm text-[#86909c] min-w-0">
            {commonPath.map((item, index) => (
                <React.Fragment key={item.id || index}>
                    {index > 0 && <span className="mx-0.5">/</span>}
                    <span className="truncate max-w-[120px]">{item.name}</span>
                </React.Fragment>
            ))}
        </div>
    );
}
