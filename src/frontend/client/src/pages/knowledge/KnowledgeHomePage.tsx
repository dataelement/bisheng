import type { KnowledgeSpace } from "~/api/knowledge";
import { MODULE_HOME_FRAME, ModuleHomeHeader } from "~/components/ModuleHome";
import { Button } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useLocalize, useWorkbenchMenuNames } from "~/hooks";
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
 * 广场 is the switcher's other half (rendered by the page, so it survives the view change);
 * 创建知识空间 is the header's action, like every module home (the 我创建的 section keeps its "+").
 */
export function KnowledgeHomePage({
    onSpaceSelect,
    onCreateSpace,
    onSpaceSettings,
    onKnowledgeSquare,
}: KnowledgeHomePageProps) {
    const localize = useLocalize();
    const menuNames = useWorkbenchMenuNames();

    return (
        <div className={MODULE_HOME_FRAME}>
            <ModuleHomeHeader title={menuNames.knowledge}>
                <Button onClick={onCreateSpace}>
                    <Outlined.Plus />
                    {localize("com_knowledge.create_knowledge_space")}
                </Button>
            </ModuleHomeHeader>
            {/* Full-bleed (cancels the frame's 12px gutters) so the list's scrollbar sits on the
                page edge; the list re-centres its content into the 1000px column itself. */}
            <div className="mt-4 min-h-0 w-[calc(100%+24px)] flex-1 overflow-hidden">
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
