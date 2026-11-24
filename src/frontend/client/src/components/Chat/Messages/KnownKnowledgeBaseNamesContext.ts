import { createContext } from "react";

export interface KnownKnowledgeBaseNames {
    /** Id -> name of the knowledge bases the user selected in the chat input. */
    names: Record<string, string>;
    /**
     * Whether a knowledge base the results never named may be looked up by id.
     * On only in the signed-in chat page; the share view stays offline.
     */
    lookupEnabled: boolean;
}

/**
 * Provided by the chat page, read by the deep-thinking knowledge rows so a
 * searched knowledge base that returned nothing still shows its name. Outside
 * the chat page it stays empty and the rows fall back to the names carried by
 * the search results.
 */
const KnownKnowledgeBaseNamesContext = createContext<KnownKnowledgeBaseNames>({
    names: {},
    lookupEnabled: false,
});

export default KnownKnowledgeBaseNamesContext;
