import type {
  Dispatch,
  MutableRefObject,
  RefObject,
  SetStateAction,
} from "react";
import type { useLocation } from "react-router-dom";
import type useAiChat from "~/hooks/useAiChat";
import type { useAuthContext } from "~/hooks/AuthContext";
import type { useGetBsConfig } from "~/hooks/queries/data-provider";
import type {
  ChatModelMode,
  readAdminDefaultModelId,
} from "~/hooks/useChatModelResolution";

export interface ChatModelSelection {
  id: number;
  name: string;
  manual?: boolean;
  mode?: ChatModelMode;
}

export interface UseTaskWorkspaceStateOptions {
  conversationId: string;
  messages: ReturnType<typeof useAiChat>["messages"];
  chatContainerRef: RefObject<HTMLDivElement>;
  isCompactLayout: boolean;
  closeCitationPanel: () => void;
  taskVersionIds: string[];
  latestTaskVersionId: string;
}

export interface UseChatModelSelectionOptions {
  conversationId: string;
  bsConfig: ReturnType<typeof useGetBsConfig>["data"];
  user: ReturnType<typeof useAuthContext>["user"];
  setChatModel: Dispatch<SetStateAction<ChatModelSelection>>;
  modelMode: ChatModelMode;
  adminDefaultModelId: ReturnType<typeof readAdminDefaultModelId>;
  taskConversationModelId: string | null;
}

export interface UseTaskModeNavigationOptions {
  location: ReturnType<typeof useLocation>;
  conversationId: string;
  setTaskMode: Dispatch<SetStateAction<boolean>>;
  keepTaskModeOnRewriteRef: MutableRefObject<boolean>;
  userToggledRef: MutableRefObject<boolean>;
  lastConversationIdRef: MutableRefObject<string | undefined>;
  canUseTaskMode: boolean;
  isTaskConversation: boolean;
}

export interface UseVisibleKnowledgeSelectionsOptions {
  user: ReturnType<typeof useAuthContext>["user"];
  selectedOrgKbs: ReturnType<typeof useAiChat>["selectedOrgKbs"];
  setSelectedOrgKbs: ReturnType<typeof useAiChat>["setSelectedOrgKbs"];
}
