import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRecoilState, useResetRecoilState, useSetRecoilState } from 'recoil';
import { checkFileParseStatus } from '~/api/linsight';
import type { TMessage } from '~/data-provider/data-provider/src';
import { QueryKeys } from '~/data-provider/data-provider/src';
import { useGetMessagesByConvoId } from '~/data-provider/data-provider/src/react-query';
import { useAuthContext } from '~/hooks/AuthContext';
import useChatFunctions from '~/hooks/Chat/useChatFunctions';
import useNewConvo from '~/hooks/useNewConvo';
import { useToastContext } from '~/Providers';
import store from '~/store';
import { filesByIndex } from '~/store/linsight';

// this to be set somewhere else
export default function useChatHelpers(index = 0, paramId?: string, isLingsight = false) {
  const clearAllSubmissions = store.useClearSubmissionState();
  const [files, setFiles] = useRecoilState(store.filesByIndex(index));
  const [linsightFiles, setLinsightFiles] = useLinsighFiles(index);

  const [filesLoading, setFilesLoading] = useState(false);

  const queryClient = useQueryClient();
  const { isAuthenticated } = useAuthContext();

  const { newConversation } = useNewConvo(index);
  const { useCreateConversationAtom } = store;
  const { conversation, setConversation } = useCreateConversationAtom(index);
  const { conversationId } = conversation ?? {};

  const queryParam = paramId === 'new' ? paramId : conversationId ?? paramId ?? '';

  /* Messages: here simply to fetch, don't export and use `getMessages()` instead */
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const { data: _messages } = useGetMessagesByConvoId(conversationId ?? '', {
    enabled: isAuthenticated,
  });

  const resetLatestMessage = useResetRecoilState(store.latestMessageFamily(index));
  const [isSubmitting, setIsSubmitting] = useRecoilState(store.isSubmittingFamily(index));
  const [latestMessage, setLatestMessage] = useRecoilState(store.latestMessageFamily(index));
  const setSiblingIdx = useSetRecoilState(
    store.messagesSiblingIdxFamily(latestMessage?.parentMessageId ?? null),
  );

  const setMessages = useCallback(
    (messages: TMessage[]) => {
      queryClient.setQueryData<TMessage[]>([QueryKeys.messages, queryParam], messages);
      if (queryParam === 'new') {
        queryClient.setQueryData<TMessage[]>([QueryKeys.messages, conversationId], messages);
      }
    },
    [queryParam, queryClient, conversationId],
  );

  const getMessages = useCallback(() => {
    return queryClient.getQueryData<TMessage[]>([QueryKeys.messages, queryParam]);
  }, [queryParam, queryClient]);

  /* Conversation */
  // const setActiveConvos = useSetRecoilState(store.activeConversations);

  // const setConversation = useCallback(
  //   (convoUpdate: TConversation) => {
  //     _setConversation(prev => {
  //       const { conversationId: convoId } = prev ?? { conversationId: null };
  //       const { conversationId: currentId } = convoUpdate;
  //       if (currentId && convoId && convoId !== 'new' && convoId !== currentId) {
  //         // for now, we delete the prev convoId from activeConversations
  //         const newActiveConvos = { [currentId]: true };
  //         setActiveConvos(newActiveConvos);
  //       }
  //       return convoUpdate;
  //     });
  //   },
  //   [_setConversation, setActiveConvos],
  // );

  const setSubmission = useSetRecoilState(store.submissionByIndex(index));

  const { ask, regenerate } = useChatFunctions({
    index,
    files: isLingsight ? linsightFiles : files,
    setFiles: isLingsight ? setLinsightFiles : setFiles,
    getMessages,
    setMessages,
    isSubmitting,
    conversation,
    latestMessage,
    setSubmission,
    setLatestMessage,
  });

  const continueGeneration = () => {
    if (!latestMessage) {
      console.error('Failed to regenerate the message: latestMessage not found.');
      return;
    }

    const messages = getMessages();

    const parentMessage = messages?.find(
      (element) => element.messageId == latestMessage.parentMessageId,
    );

    if (parentMessage && parentMessage.isCreatedByUser) {
      ask({ ...parentMessage }, { isContinued: true, isRegenerate: true, isEdited: true });
    } else {
      console.error(
        'Failed to regenerate the message: parentMessage not found, or not created by user.',
      );
    }
  };

  const stopGenerating = () => clearAllSubmissions();

  const handleStopGenerating = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    stopGenerating();
  };

  const handleRegenerate = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    const parentMessageId = latestMessage?.parentMessageId ?? '';
    if (!parentMessageId) {
      console.error('Failed to regenerate the message: parentMessageId not found.');
      return;
    }
    regenerate({ parentMessageId });
  };

  const handleContinue = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.preventDefault();
    continueGeneration();
    setSiblingIdx(0);
  };

  const [showPopover, setShowPopover] = useRecoilState(store.showPopoverFamily(index));
  const [abortScroll, setAbortScroll] = useRecoilState(store.abortScrollFamily(index));
  const [preset, setPreset] = useRecoilState(store.presetByIndex(index));
  const [optionSettings, setOptionSettings] = useRecoilState(store.optionSettingsFamily(index));
  const [showAgentSettings, setShowAgentSettings] = useRecoilState(
    store.showAgentSettingsFamily(index),
  );

  return {
    newConversation,
    conversation,
    setConversation,
    // getConvos,
    // setConvos,
    isSubmitting,
    setIsSubmitting,
    getMessages,
    setMessages,
    setSiblingIdx,
    latestMessage,
    setLatestMessage,
    resetLatestMessage,
    ask,
    index,
    regenerate,
    stopGenerating,
    handleStopGenerating,
    handleRegenerate,
    handleContinue,
    showPopover,
    setShowPopover,
    abortScroll,
    setAbortScroll,
    preset,
    setPreset,
    optionSettings,
    setOptionSettings,
    showAgentSettings,
    setShowAgentSettings,
    files: isLingsight ? linsightFiles : files,
    setFiles: isLingsight ? setLinsightFiles : setFiles,
    filesLoading,
    setFilesLoading
  };
}



const useLinsighFiles = (index) => {
  const [files, setLinsightFiles] = useRecoilState(filesByIndex(index));
  const filesRef = useRef(new Map()); // 用于跟踪文件状态

  const { showToast } = useToastContext();

  const newFiles = useMemo(() => {
    const newFiles = new Map(files);

    newFiles.forEach((value, key) => {
      newFiles.set(key, {
        ...value,
        progress: value.parsing_status === 'completed' ? 1 : 0.9,
        parsing_status: value.parsing_status ?? 'pending'
      });
    });

    filesRef.current = newFiles;
    return newFiles;
  }, [files]);


  // 解析状态检查定时器
  useEffect(() => {
    const intervalId = setInterval(async () => {
      const currentFiles = new Map(filesRef.current);
      const filesToCheck = [];

      // 收集需要检查的文件：上传完成但未解析完成的文件
      currentFiles.forEach(file => {
        if (!['failed', 'completed'].includes(file.parsing_status)) {
          file.file_id.indexOf('-') === -1 && filesToCheck.push(file.file_id);
        }
      });

      if (filesToCheck.length === 0) return;

      try {
        const res = await checkFileParseStatus(filesToCheck);
        const statusMap = new Map(res.data.map(item => [item.file_id, item.parsing_status]));

        setLinsightFiles(_updatedFiles => {
          const updatedFiles = new Map(_updatedFiles);
          // 遍历 updatedFiles，找到匹配 fileId 的文件
          updatedFiles.forEach((file, key) => {
            const fileId = file.file_id; // 假设 file 对象中有 file_id 字段
            if (statusMap.has(fileId)) {
              const status = statusMap.get(fileId);
              if (status === 'completed' && file.parsing_status !== 'completed') {
                updatedFiles.set(key, {
                  ...file,
                  parsing_status: 'completed',
                  // 可添加其他解析完成后的元数据
                });
              } else if (status === 'failed') {
                updatedFiles.delete(key);
                showToast({ message: `文件 ${file.filename} 解析失败, 自动移除`, status: 'error' });
              }
            }
          });

          return updatedFiles
        })
      } catch (error) {
        console.error('文件解析状态检查失败:', error);
      }
    }, 2000)
    return () => clearInterval(intervalId);
  }, []);

  return [newFiles, setLinsightFiles]
}
