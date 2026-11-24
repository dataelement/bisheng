import { createContext } from "react";

/**
 * Id -> name of the knowledge bases the user selected in the chat input.
 * Provided by the chat page; read by the deep-thinking knowledge rows so a
 * searched knowledge base that returned nothing still shows its name.
 * Outside the chat page (share view, panels) it stays empty and the rows fall
 * back to the names carried by the search results.
 */
const KnownKnowledgeBaseNamesContext = createContext<Record<string, string>>({});

export default KnownKnowledgeBaseNamesContext;
