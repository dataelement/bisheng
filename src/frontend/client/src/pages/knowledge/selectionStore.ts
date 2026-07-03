import { atom } from "recoil";

/**
 * Selected file ids in the knowledge-space file list.
 *
 * Shared (rather than local to KnowledgeSpaceContent) so sibling components —
 * notably the bottom AI dock — can clear the selection without prop drilling.
 * Rationale: file selection (batch ops) and AI Q&A are independent; focusing or
 * sending in the AI input is a "context switch" that clears any lingering
 * selection, so the two never appear coupled to the user.
 */
export const knowledgeSelectedFilesState = atom<Set<string>>({
    key: "knowledgeSelectedFilesState",
    default: new Set<string>(),
});
