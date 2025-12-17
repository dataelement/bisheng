import { useCallback } from 'react';
import { useRecoilState, useRecoilValue, useSetRecoilState } from 'recoil';
import { v4 } from 'uuid';
import { useAddedChatContext, useChatContext, useChatFormContext } from '~/Providers';
import { sameSopLabelState } from '~/components/Chat/Input/SameSopSpan';
import { Constants } from '~/data-provider/data-provider/src';
import { useAuthContext } from '~/hooks/AuthContext';
import store from '~/store';
import { replaceSpecialVars } from '~/utils';
import { useSetFilesToDelete } from '../Files';
import { useLinsightSessionManager } from '../useLinsightManager';

const appendIndex = (index: number, value?: string) => {
  if (!value) {
    return value;
  }
  return `${value}${Constants.COMMON_DIVIDER}${index}`;
};

export default function useSubmitMessage(helpers?: { clearDraft?: () => void }) {
  const { user } = useAuthContext();
  const methods = useChatFormContext();
  const { files, setFiles, ask, index, getMessages, setMessages, latestMessage } = useChatContext();
  const { addedIndex, ask: askAdditional, conversation: addedConvo } = useAddedChatContext();

  const autoSendPrompts = useRecoilValue(store.autoSendPrompts);
  const activeConvos = useRecoilValue(store.allConversationsSelector);
  const setActivePrompt = useSetRecoilState(store.activePromptByIndex(index));
  const { setLinsightSubmission } = useLinsightSessionManager('new')
  const setFilesToDelete = useSetFilesToDelete();
  const [sameSopLabel, setSameSopLabel] = useRecoilState(sameSopLabelState)

  const submitMessage = useCallback(
    (data?: { text: string, linsight?: boolean, tools?: any[],knowledge?: {
    personal?: boolean;
    orgKbIds?: string[];
  }; }) => {
      if (!data) {
        return console.warn('No data provided to submitMessage');
      }

      if (data?.linsight) {
        setLinsightSubmission('new', {
          sameSopId: sameSopLabel?.id || undefined,
          isNew: true,
          files: Array.from(files.values()).map(item => ({
            file_id: item.file_id,
            file_name: item.filename,
            parsing_status: 'completed'
          })),
          question: data?.text,
          // feedback: '',
          tools: data.tools,
          model: 'gpt-4',
          enableWebSearch: false,
          useKnowledgeBase: true,
          orgKnowledgeBaseIds: data.knowledge?.orgKbIds ?? [],
        });
        // 重置表单和清理草稿
        methods.reset();
        setFiles(new Map())
        setFilesToDelete({});
        helpers?.clearDraft && helpers.clearDraft();
        return setSameSopLabel(null);
      }
      // 检查最新消息是否在会话中
      const rootMessages = getMessages();
      const isLatestInRootMessages = rootMessages?.some(
        (message) => message.messageId === latestMessage?.messageId,
      );
      if (!isLatestInRootMessages && latestMessage) {
        setMessages([...(rootMessages || []), latestMessage]);
      }
      // 处理会话 ID 和消息 ID 的逻辑
      const hasAdded = addedIndex && activeConvos[addedIndex] && addedConvo;
      const isNewMultiConvo =
        hasAdded &&
        activeConvos.every((convoId) => convoId === Constants.NEW_CONVO) &&
        !rootMessages?.length;
      const overrideConvoId = isNewMultiConvo ? v4() : undefined;
      const overrideUserMessageId = hasAdded ? v4() : undefined;
      const rootIndex = addedIndex - 1;
      const clientTimestamp = new Date().toISOString();
      // 发送消息
      ask({
        text: data.text,
        overrideConvoId: appendIndex(rootIndex, overrideConvoId),
        overrideUserMessageId: appendIndex(rootIndex, overrideUserMessageId),
        clientTimestamp,
      });

      // 处理附加消息（如果有）
      if (hasAdded) {
        askAdditional(
          {
            text: data.text,
            overrideConvoId: appendIndex(addedIndex, overrideConvoId),
            overrideUserMessageId: appendIndex(addedIndex, overrideUserMessageId),
            clientTimestamp,
          },
          { overrideMessages: rootMessages },
        );
      }
      // 重置表单和清理草稿
      methods.reset();
      helpers?.clearDraft && helpers.clearDraft();
    },
    [
      ask,
      methods,
      helpers,
      addedIndex,
      addedConvo,
      setMessages,
      getMessages,
      activeConvos,
      askAdditional,
      latestMessage,
    ],
  );

  const submitPrompt = useCallback(
    (text: string) => {
      const parsedText = replaceSpecialVars({ text, user });
      if (autoSendPrompts) {
        submitMessage({ text: parsedText });
        return;
      }

      const currentText = methods.getValues('text');
      const newText = currentText.trim().length > 1 ? `\n${parsedText}` : parsedText;
      setActivePrompt(newText);
    },
    [autoSendPrompts, submitMessage, setActivePrompt, methods, user],
  );

  return { submitMessage, submitPrompt };
}
