export type ChatMode = 'workflow' | 'assistant';
export type MessageKind = 'user' | 'answer' | 'run' | 'form' | 'choice' | 'system' | 'file' | 'unknown' | 'hidden' | 'reasoning';
export type RawMessage = Record<string, unknown>;
export interface ChatAttachment {
  id?: string;
  name: string;
  url: string;
  raw: RawMessage;
}
export interface ChatMessage {
  key: string;
  sourceMessageId?: string;
  parentMessageId?: string;
  turnId?: string;
  kind: MessageKind;
  category: string;
  text: string;
  reasoning: string;
  payload: unknown;
  files: ChatAttachment[];
  final: boolean;
  raw: RawMessage;
  issues: string[];
}
export interface HistoryOptions {
  mode: ChatMode;
  sessionKey: string;
  pageKey?: string;
}
export interface ConversationSnapshot {
  sessionKey: string;
  messages: ChatMessage[];
  running: boolean;
  error: string | null;
}
export type ConversationEvent = {
  type: 'message'; sessionKey: string; key: string; sourceMessageId?: string;
  category: string; text: string; reasoning?: string; operation: 'append' | 'replace';
  final: boolean; raw?: RawMessage;
} | { type: 'running'; sessionKey: string; running: boolean }
  | { type: 'error'; sessionKey: string; error: string | null }
  | { type: 'history'; sessionKey: string; messages: ChatMessage[]; prepend: boolean }
  | { type: 'clear'; sessionKey: string };
export interface QaPair {
  question: string;
  answer: string;
  sourceMessageId?: string;
  questionMessageId?: string;
}
export interface QaOperation {
  taskId: string;
  conversationId: string;
  sourceMessageId: string;
  actionId: string;
  sessionGeneration: number;
}
