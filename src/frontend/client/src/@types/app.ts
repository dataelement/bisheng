/** Application item from API (frequently_used / chat_online response) */
export interface AppItem {
  id: string;
  name: string;
  description: string;
  logo: string;
  flow_type: number; // 1=skill, 5=assistant, 10=workflow, 35=hosted application
  tags?: TagItem[];
  user_id: string;
  is_pinned?: boolean; // Pinned state from backend
  last_chat_time?: string; // ISO date of last conversation
  last_chat_id?: string; // Last conversation ID (for "continue chat")
  /** ReBAC relation-model ``share_app`` — hide share UI when false */
  can_share?: boolean;
  /**
   * Hosted applications only (flow_type 35). Entry path segment: the card opens
   * `/apps/{slug}`, which is served outside this SPA.
   */
  slug?: string;
  /**
   * Hosted applications only. The square lists exactly these two states —
   * stopped stays on the wall with a badge, because hiding it reads as "I lost
   * access" rather than "this app is paused".
   */
  app_state?: 'online' | 'stopped';
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
