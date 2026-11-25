import { useLayoutEffect, useRef } from 'react';
import type { ChatMessage } from '~/api/chatApi';
import { useConfirm } from '~/Providers';
import { useLocalize } from '~/hooks';

export type RetryMaterials = 'original' | 'current';
export type RetryRequest = { questionId: string; materials: RetryMaterials };
export type SendOptions = { taskMode?: boolean; retry?: RetryRequest };

interface DailyRetryOptions {
  bucket: string;
  userId?: string;
  readOnly: boolean;
  streaming: boolean;
  messages: ChatMessage[];
  send: (text: string, files?: ChatMessage['files'], options?: SendOptions) => Promise<boolean>;
}

/** Only the server can vouch for the original materials. Never reconstruct them from today's picker. */
export function useDailyRegenerate(options: DailyRetryOptions) {
  const confirm = useConfirm();
  const localize = useLocalize();
  const latest = useRef(options);
  latest.current = options;
  const generation = useRef(0);
  const pending = useRef(false);
  useLayoutEffect(() => () => { generation.current++; pending.current = false; }, [options.bucket, options.userId, options.readOnly]);

  return async (parentId: string, materials: RetryMaterials = 'original') => {
    if (pending.current || options.streaming || options.readOnly) return;
    const question = options.messages.find(row => row.isCreatedByUser && row.messageId === parentId);
    if (!question) return;
    const persisted = /^\d+$/.test(question.messageId);
    const token = generation.current;
    pending.current = true;
    try {
      // No saved ID (including optimistic UUIDs) means even an explicit re-ask
      // must be a fresh submission, never a fabricated server retry target.
      if (!persisted || question.knowledge_scope_recorded !== true) {
        if (!await confirm({
          title: localize('com_message.original_materials_unavailable'),
          description: localize('com_message.current_materials_confirm'),
          confirmText: localize('com_message.ask_current_materials'),
        })) return;
        materials = 'current';
      }
      const now = latest.current;
      if (generation.current !== token || now.streaming || now.readOnly || !now.messages.includes(question)) return;
      await now.send(question.text, question.files, persisted ? { retry: { questionId: parentId, materials } } : undefined);
    } finally {
      if (generation.current === token) pending.current = false;
    }
  };
}
