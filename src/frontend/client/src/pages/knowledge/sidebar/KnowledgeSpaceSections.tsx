import { Button, Segmented, Tooltip } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { getKnowledgeListTab } from "../knowledgeListNavigation";
import type { KnowledgeSpace, SpaceSortType } from "~/api/knowledge";
import { knowledgeSpaceDropdownSurfaceClassName } from "~/components/SidebarListMoreMenu";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { KnowledgeSpaceGhostTile } from "./KnowledgeSpaceGhostTile";
import { SectionHeader } from "./SectionHeader";

type SpaceSectionType = "department" | "created" | "joined";

export type KnowledgeSpaceSection = {
    type: SpaceSectionType;
    title: string;
    spaces: KnowledgeSpace[];
    collapsed: boolean;
    onToggle: () => void;
    sortValue: SpaceSortType;
};

interface KnowledgeSpaceSectionsProps {
    sections: KnowledgeSpaceSection[];
    sortOptions: { value: SpaceSortType; label: string }[];
    onSortChange: (type: SpaceSectionType, value: SpaceSortType) => void;
    renderSpaceItem: (space: KnowledgeSpace, type: SpaceSectionType) => ReactNode;
    onCreateSpace: () => void;
    onKnowledgeSquare?: () => void;
    compactMode: boolean;
    mobilePageMode: boolean;
    pageGrid: boolean;
}

export function KnowledgeSpaceSections({
    sections,
    sortOptions,
    onSortChange,
    renderSpaceItem,
    onCreateSpace,
    onKnowledgeSquare,
    compactMode,
    mobilePageMode,
    pageGrid,
}: KnowledgeSpaceSectionsProps) {
    const localize = useLocalize();
    const [searchParams, setSearchParams] = useSearchParams();
    const activeSection = getKnowledgeListTab(searchParams.toString());
    const sortFieldLabel = localize("com_knowledge.sort_field");
    // Keep empty content aligned to the visible tree viewport during horizontal scroll.
    const pinnedEmptyClassName = "sticky left-0 -mx-3 w-[100cqi]";

    const renderEmptyState = (stretch: boolean) => (
        <div className={cn(
            "flex items-center justify-center text-center text-body text-text-3",
            !mobilePageMode && pinnedEmptyClassName,
            pageGrid && "col-span-full",
            compactMode ? "py-6" : stretch ? "flex-1 py-6" : "h-24",
        )}>
            {localize("com_knowledge.no_data")}
        </div>
    );

    if (pageGrid) {
        const section = sections.find((item) => item.type === activeSection) ?? sections[0];
        if (!section) return null;

        return (
            <section className="pb-4">
                <div className="sticky top-0 z-[2] flex items-center justify-between gap-3 bg-bg-page py-2">
                    <div className="min-w-0 overflow-x-auto py-1">
                        <Segmented
                            aria-label={localize("com_knowledge.knowledge_space")}
                            options={sections.map((item) => ({ value: item.type, label: item.title }))}
                            value={section.type}
                            onChange={(value) => {
                                const next = sections.find((item) => item.type === value);
                                if (next) {
                                    setSearchParams((previous) => {
                                        const params = new URLSearchParams(previous);
                                        params.set("tab", next.type);
                                        return params;
                                    }, { replace: true });
                                }
                            }}
                        />
                    </div>
                    <DropdownMenu>
                        <Tooltip content={sortFieldLabel}>
                            <DropdownMenuTrigger asChild>
                                <Button color="default" variant="text" iconOnly aria-label={sortFieldLabel}>
                                    <Outlined.Sort />
                                </Button>
                            </DropdownMenuTrigger>
                        </Tooltip>
                        <DropdownMenuContent align="end" className={knowledgeSpaceDropdownSurfaceClassName}>
                            <div className="px-2 py-1.5 text-caption font-medium text-text-3">{sortFieldLabel}</div>
                            {sortOptions.map((option) => (
                                <DropdownMenuItem
                                    key={option.value}
                                    onSelect={() => onSortChange(section.type, option.value)}
                                    className="flex items-center justify-between gap-6"
                                >
                                    <span>{option.label}</span>
                                    {option.value === section.sortValue && <Outlined.Check className="size-4 shrink-0" />}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
                <div
                    role="region"
                    aria-label={section.title}
                    className="grid w-[100cqi] grid-cols-[repeat(auto-fill,minmax(128px,1fr))] gap-5 py-3"
                >
                    {section.type === "created" && (
                        <KnowledgeSpaceGhostTile
                            tone="created"
                            label={localize("com_knowledge.create_knowledge_space")}
                            onClick={onCreateSpace}
                        />
                    )}
                    {section.type === "joined" && (
                        <KnowledgeSpaceGhostTile
                            tone="joined"
                            label={localize("com_knowledge.go_to_knowledge_square")}
                            onClick={() => onKnowledgeSquare?.()}
                        />
                    )}
                    {section.spaces.map((space) => renderSpaceItem(space, section.type))}
                    {section.type === "department" && section.spaces.length === 0 && renderEmptyState(false)}
                </div>
            </section>
        );
    }

    // File-page dropdowns and mobile lists retain their existing collapsible sections.
    return (
        <>
            {sections.map((section) => {
                const stretch = !compactMode && section.type === "joined" && !section.collapsed;
                return (
                    <div key={section.type} className={cn("pb-4", stretch && "flex flex-1 flex-col")}>
                        <SectionHeader
                            title={section.title}
                            collapsed={section.collapsed}
                            onToggle={section.onToggle}
                            sortValue={section.sortValue}
                            sortOptions={sortOptions}
                            sortFieldLabel={sortFieldLabel}
                            onSortChange={(value) => onSortChange(section.type, value as SpaceSortType)}
                            onAdd={section.type === "created" ? onCreateSpace : undefined}
                            addLabel={localize("com_knowledge.create")}
                            onSquare={compactMode && section.type === "joined" ? onKnowledgeSquare : undefined}
                            squareLabel={localize("com_knowledge.go_to_square")}
                            compact={compactMode}
                            mobile={mobilePageMode}
                        />
                        {!section.collapsed && (
                            <div className={cn(
                                compactMode ? "space-y-1 px-3" : mobilePageMode ? "w-[100cqi] px-4 py-2" : "space-y-0.5 px-3",
                                stretch && "flex flex-1 flex-col",
                            )}>
                                {section.spaces.map((space) => renderSpaceItem(space, section.type))}
                                {section.spaces.length === 0 && renderEmptyState(stretch)}
                            </div>
                        )}
                    </div>
                );
            })}
        </>
    );
}
