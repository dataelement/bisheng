import { KnowledgeSpaceSummary } from "@/controllers/API/knowledgeSpace";

export interface KnowledgeSpaceOption {
    label: string;
    value: number;
    spaceLevel: KnowledgeSpaceLevel;
}

type KnowledgeSpaceLevel = "public" | "department" | "team" | "personal";

const SPACE_LEVELS: KnowledgeSpaceLevel[] = ["public", "department", "team", "personal"];

const toSpaceLevel = (spaceLevel?: string): KnowledgeSpaceLevel => {
    return SPACE_LEVELS.includes(spaceLevel as KnowledgeSpaceLevel)
        ? spaceLevel as KnowledgeSpaceLevel
        : "personal";
};

export const toKnowledgeSpaceOption = (space: KnowledgeSpaceSummary): KnowledgeSpaceOption => ({
    label: space.name,
    value: space.id,
    spaceLevel: toSpaceLevel(space.space_level),
});

export const buildKnowledgeSpaceGroups = (
    options: KnowledgeSpaceOption[],
    t: (key: string) => string,
) => SPACE_LEVELS.map((level) => ({
    value: level,
    label: t(`knowledgeSpaceLevel.${level}`),
    options: options.filter((option) => option.spaceLevel === level),
})).filter((group) => group.options.length > 0);
