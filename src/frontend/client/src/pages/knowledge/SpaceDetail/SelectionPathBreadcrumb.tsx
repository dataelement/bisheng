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
 * Clicking any segment (including last) opens the folder in a new tab.
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

    // When a single file is selected, show full path without truncation
    const isSingle = selectedFiles.size === 1;

    /** Build the URL for a given folder and open in a new tab */
    const handleNavigate = (folderId: string | undefined) => {
        const base = `${__APP_ENV__.BASE_URL}/knowledge/space/${spaceId}`;
        const url = folderId ? `${base}/folder/${folderId}` : base;
        window.open(url, "_blank");
    };

    return (
        <div className="flex items-center gap-0.5 text-sm text-[#86909c] min-w-0">
            {commonPath.map((item, index) => {
                const isLast = index === commonPath.length - 1;
                return (
                    <React.Fragment key={item.id || index}>
                        {index > 0 && <span className="mx-0.5">/</span>}
                        <button
                            type="button"
                            onClick={() => handleNavigate(item.id || undefined)}
                            className={`hover:text-[#165dff] hover:underline cursor-pointer ${isLast && !isSingle ? "truncate max-w-[120px]" : "whitespace-nowrap"}`}
                        >
                            {item.name}
                        </button>
                    </React.Fragment>
                );
            })}
        </div>
    );
}

