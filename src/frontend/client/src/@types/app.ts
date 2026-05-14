/** Application item from API (frequently_used / chat_online response) */
export interface AppItem {
  id: string;
  name: string;
  description: string;
  logo: string;
  flow_type: number; // 1=skill, 5=assistant, 10=workflow
  tags?: TagItem[];
  user_id: string;
  is_pinned?: boolean; // Pinned state from backend
  last_chat_time?: string; // ISO date of last conversation
  last_chat_id?: string; // Last conversation ID (for "continue chat")
}

/** Tag/category */
export interface TagItem {
  id: number;
  name: string;
}

/** Conversation item for app sidebar */
export interface AppConversation {
  id: string; // chatId / conversationId
  title: string;
  flowId: string;
  flowType: number;
  updatedAt: string; // ISO date
  createdAt: string; // ISO date
}

/** Time group for conversation list */
export interface ConversationGroup {
  label: string; // e.g. "今天", "昨天", "过去 7 天"
  conversations: AppConversation[];
}
