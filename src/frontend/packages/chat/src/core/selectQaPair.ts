import type { ChatMessage, QaOperation, QaPair } from './types';
export function selectQaPair(messages: readonly ChatMessage[], selectedKey: string): QaPair | null {
  const index = messages.findIndex(message => message.key === selectedKey);
  const selected = messages[index];
  if (!selected || !['user', 'answer'].includes(selected.kind)) return null;
  let question = selected.kind === 'user' ? selected : undefined;
  if (!question && selected.parentMessageId !== undefined) {
    question = messages.slice(0, index).find(item => item.kind === 'user' && item.sourceMessageId === selected.parentMessageId);
  }
  if (!question && selected.turnId !== undefined) {
    question = messages.slice(0, index).find(item => item.kind === 'user' && item.turnId === selected.turnId);
  }
  if (!question) {
    for (let cursor = index - 1; cursor >= 0; cursor--) {
      if (messages[cursor].kind === 'user') { question = messages[cursor]; break; }
    }
  }
  if (!question) return null;
  return { question: question.text, answer: selected.kind === 'answer' ? selected.text : '',
    sourceMessageId: selected.sourceMessageId, questionMessageId: question.sourceMessageId };
}
export function captureQaOperation(context: QaOperation): Readonly<QaOperation> { return Object.freeze({ ...context }); }
export function isCurrentQaOperation(origin: QaOperation, current: QaOperation | null | undefined): boolean {
  return !!current && origin.taskId === current.taskId && origin.conversationId === current.conversationId
    && origin.sourceMessageId === current.sourceMessageId && origin.actionId === current.actionId
    && origin.sessionGeneration === current.sessionGeneration;
}
