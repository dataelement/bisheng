import type { KnowledgeSpace } from "~/api/knowledge";
import { MODULE_HOME_COLUMN, MODULE_HOME_FRAME, ModuleHomeHeader } from "~/components/ModuleHome";
import { useWorkbenchMenuNames } from "~/hooks";
import { cn } from "~/utils";
import { KnowledgeSpaceSidebar } from "./sidebar/KnowledgeSpaceSidebar";

interface KnowledgeHomePageProps {
    /** Null when the active space went away (deleted / left) — same contract as the list. */
    onSpaceSelect: (space: KnowledgeSpace | null) => void;
    onCreateSpace: () => void;
    onSpaceSettings: (space: KnowledgeSpace) => void;
    onKnowledgeSquare: () => void;
}

/**
 * Desktop 知识空间 · 我的 view (see ~/components/ModuleHome for the shared frame): the
 * mobile list page's desktop counterpart — same sections, sort, pin and per-space
 * actions, all owned by KnowledgeSpaceSidebar's page mode — laid out as a card grid.
 * The header carries no buttons: 广场 is the switcher's other half (rendered by the page,
 * so it survives the view change), and 创建 is the "+" on the 我创建的 section.
 */
export function KnowledgeHomePage({
    onSpaceSelect,
    onCreateSpace,
    onSpaceSettings,
    onKnowledgeSquare,
}: KnowledgeHomePageProps) {
    const menuNames = useWorkbenchMenuNames();

    return (
        <div className={MODULE_HOME_FRAME}>
            <ModuleHomeHeader title={menuNames.knowledge} />
            <div className={cn(MODULE_HOME_COLUMN, "mt-4 min-h-0 flex-1 overflow-hidden")}>
                <KnowledgeSpaceSidebar
                    mobilePageMode
                    pageGrid
                    onSpaceSelect={onSpaceSelect}
                    onCreateSpace={onCreateSpace}
                    onSpaceSettings={onSpaceSettings}
                    onKnowledgeSquare={onKnowledgeSquare}
                />
            </div>
        </div>
    );
}
