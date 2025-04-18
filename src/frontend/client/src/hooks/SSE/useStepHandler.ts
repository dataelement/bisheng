import { useCallback, useRef } from 'react';
import { StepTypes, ContentTypes, ToolCallTypes, getNonEmptyValue } from '~/data-provider/data-provider/src';
import type {
  Agents,
  TMessage,
  PartMetadata,
  EventSubmission,
  TMessageContentParts,
} from '~/data-provider/data-provider/src';
import type { SetterOrUpdater } from 'recoil';
import type { AnnounceOptions } from '~/common';
import { MESSAGE_UPDATE_INTERVAL } from '~/common';

// useStepHandler hook的参数类型定义
type TUseStepHandler = {
  announcePolite: (options: AnnounceOptions) => void; // 提示消息的函数（例如“正在撰写”）
  setMessages: (messages: TMessage[]) => void; // 设置/更新消息列表的函数
  getMessages: () => TMessage[] | undefined; // 获取当前消息列表的函数
  setIsSubmitting: SetterOrUpdater<boolean>; // 设置提交状态（是否正在提交）
  lastAnnouncementTimeRef: React.MutableRefObject<number>; // 用于存储上次提示时间的引用
};

// 事件传递给处理函数的类型定义
type TStepEvent = {
  event: string; // 事件类型（例如 'on_run_step'，'on_message_delta'）
  data:
    | Agents.MessageDeltaEvent
    | Agents.RunStep
    | Agents.ToolEndEvent
    | { runId?: string; message: string }; // 事件相关的数据
};

// 消息内容更新的类型定义
type MessageDeltaUpdate = { type: ContentTypes.TEXT; text: string; tool_call_ids?: string[] };
type ReasoningDeltaUpdate = { type: ContentTypes.THINK; think: string };

// 消息内容的所有可能类型
type AllContentTypes =
  | ContentTypes.TEXT
  | ContentTypes.THINK
  | ContentTypes.TOOL_CALL
  | ContentTypes.IMAGE_FILE
  | ContentTypes.IMAGE_URL
  | ContentTypes.ERROR;

export default function useStepHandler({
  setMessages,
  getMessages,
  setIsSubmitting,
  announcePolite,
  lastAnnouncementTimeRef,
}: TUseStepHandler) {
  // 用于存储工具调用ID、消息对象和步骤数据的引用
  const toolCallIdMap = useRef(new Map<string, string | undefined>());
  const messageMap = useRef(new Map<string, TMessage>());
  const stepMap = useRef(new Map<string, Agents.RunStep>());

  // 根据新的内容更新消息的函数
  const updateContent = (
    message: TMessage,
    index: number,
    contentPart: Agents.MessageContentComplex,
    finalUpdate = false,
  ) => {
    const contentType = contentPart.type ?? ''; // 获取内容类型
    if (!contentType) {
      console.warn('No content type found in content part');
      return message;
    }

    const updatedContent = [...(message.content || [])] as Array<
      Partial<TMessageContentParts> | undefined
    >;
    if (!updatedContent[index]) {
      updatedContent[index] = { type: contentPart.type as AllContentTypes };
    }

    // 处理不同的内容类型，并根据内容类型更新消息
    if (
      contentType.startsWith(ContentTypes.TEXT) &&
      ContentTypes.TEXT in contentPart &&
      typeof contentPart.text === 'string'
    ) {
      const currentContent = updatedContent[index] as MessageDeltaUpdate;
      const update: MessageDeltaUpdate = {
        type: ContentTypes.TEXT,
        text: (currentContent.text || '') + contentPart.text, // 拼接文本
      };

      if (contentPart.tool_call_ids != null) {
        update.tool_call_ids = contentPart.tool_call_ids; // 存储工具调用ID（如果存在）
      }
      updatedContent[index] = update;
    } else if (
      contentType.startsWith(ContentTypes.THINK) &&
      ContentTypes.THINK in contentPart &&
      typeof contentPart.think === 'string'
    ) {
      const currentContent = updatedContent[index] as ReasoningDeltaUpdate;
      const update: ReasoningDeltaUpdate = {
        type: ContentTypes.THINK,
        think: (currentContent.think || '') + contentPart.think, // 拼接推理内容
      };

      updatedContent[index] = update;
    } else if (contentType === ContentTypes.IMAGE_URL && 'image_url' in contentPart) {
      const currentContent = updatedContent[index] as {
        type: ContentTypes.IMAGE_URL;
        image_url: string;
      };
      updatedContent[index] = {
        ...currentContent,
      };
    } else if (contentType === ContentTypes.TOOL_CALL && 'tool_call' in contentPart) {
      const existingContent = updatedContent[index] as Agents.ToolCallContent | undefined;
      const existingToolCall = existingContent?.tool_call;
      const toolCallArgs = (contentPart.tool_call.args as unknown as string | undefined) ?? '';

      const args = finalUpdate
        ? contentPart.tool_call.args
        : (existingToolCall?.args ?? '') + toolCallArgs; // 如果不是最后更新，则拼接参数

      const id = getNonEmptyValue([contentPart.tool_call.id, existingToolCall?.id]) ?? '';
      const name = getNonEmptyValue([contentPart.tool_call.name, existingToolCall?.name]) ?? '';

      const newToolCall: Agents.ToolCall & PartMetadata = {
        id,
        name,
        args,
        type: ToolCallTypes.TOOL_CALL,
        auth: contentPart.tool_call.auth,
        expires_at: contentPart.tool_call.expires_at,
      };

      if (finalUpdate) {
        newToolCall.progress = 1; // 如果是最终更新，则设置进度为100%
        newToolCall.output = contentPart.tool_call.output; // 存储工具调用的输出（如果是最终更新）
      }

      updatedContent[index] = {
        type: ContentTypes.TOOL_CALL,
        tool_call: newToolCall,
      };
    }

    return { ...message, content: updatedContent as TMessageContentParts[] }; // 返回更新后的消息
  };

  return useCallback(
    // 接受step的事件处理回调
    ({ event, data }: TStepEvent, submission: EventSubmission) => {
      const messages = getMessages() || []; // 获取当前的消息列表
      const { userMessage } = submission;
      setIsSubmitting(true); // 设置提交状态为正在提交

      const currentTime = Date.now();
      if (currentTime - lastAnnouncementTimeRef.current > MESSAGE_UPDATE_INTERVAL) {
        announcePolite({ message: 'composing', isStatus: true }); // 提示“正在撰写”状态
        lastAnnouncementTimeRef.current = currentTime;
      }

      // 处理不同的事件类型
      if (event === 'on_run_step') {
        // 处理'on_run_step'事件
        const runStep = data as Agents.RunStep;
        const responseMessageId = runStep.runId ?? '';
        if (!responseMessageId) {
          console.warn('未找到消息ID');
          return;
        }

        stepMap.current.set(runStep.id, runStep); // 存储步骤数据
        let response = messageMap.current.get(responseMessageId);

        // 如果响应消息不存在，则创建一个新的响应消息
        if (!response) {
          const responseMessage = messages[messages.length - 1] as TMessage;

          response = {
            ...responseMessage,
            parentMessageId: userMessage.messageId,
            conversationId: userMessage.conversationId,
            messageId: responseMessageId,
            content: [],
          };

          messageMap.current.set(responseMessageId, response);
          setMessages([...messages.slice(0, -1), response]);
        }

        // 如果步骤涉及到工具调用，存储工具调用ID
        if (runStep.stepDetails.type === StepTypes.TOOL_CALLS) {
          runStep.stepDetails.tool_calls.forEach((toolCall) => {
            const toolCallId = toolCall.id ?? '';
            if ('id' in toolCall && toolCallId) {
              toolCallIdMap.current.set(runStep.id, toolCallId);
            }
          });
        }
      } else if (event === 'on_agent_update') {
        // 处理'on_agent_update'事件（代理更新）
        const { runId, message } = data as { runId?: string; message: string };
        const responseMessageId = runId ?? '';
        if (!responseMessageId) {
          console.warn('No message id found in agent update event');
          return;
        }

        const responseMessage = messages[messages.length - 1] as TMessage;

        const response = {
          ...responseMessage,
          parentMessageId: userMessage.messageId,
          conversationId: userMessage.conversationId,
          messageId: responseMessageId,
          content: [
            {
              type: ContentTypes.TEXT,
              text: message,
            },
          ],
        } as TMessage;

        setMessages([...messages.slice(0, -1), response]); // 更新消息
      } else if (event === 'on_message_delta') {
        // 处理'on_message_delta'事件（消息增量更新）
        const messageDelta = data as Agents.MessageDeltaEvent;
        const runStep = stepMap.current.get(messageDelta.id);
        const responseMessageId = runStep?.runId ?? '';

        if (!runStep || !responseMessageId) {
          console.warn('未找到运行步骤或消息ID');
          return;
        }

        const response = messageMap.current.get(responseMessageId);
        if (response && messageDelta.delta.content) {
          const contentPart = Array.isArray(messageDelta.delta.content)
            ? messageDelta.delta.content[0]
            : messageDelta.delta.content;

          const updatedResponse = updateContent(response, runStep.index, contentPart);

          messageMap.current.set(responseMessageId, updatedResponse); // 更新响应消息
          const currentMessages = getMessages() || [];
          setMessages([...currentMessages.slice(0, -1), updatedResponse]); // 更新消息状态
        }
      } else if (event === 'on_reasoning_delta') {
        // 处理'on_reasoning_delta'事件（推理增量更新）
        const reasoningDelta = data as Agents.ReasoningDeltaEvent;
        const runStep = stepMap.current.get(reasoningDelta.id);
        const responseMessageId = runStep?.runId ?? '';

        if (!runStep || !responseMessageId) {
          console.warn('No run step or runId found for reasoning delta event');
          return;
        }

        const response = messageMap.current.get(responseMessageId);
        if (response && reasoningDelta.delta.content != null) {
          const contentPart = Array.isArray(reasoningDelta.delta.content)
            ? reasoningDelta.delta.content[0]
            : reasoningDelta.delta.content;

          const updatedResponse = updateContent(response, runStep.index, contentPart);

          messageMap.current.set(responseMessageId, updatedResponse); // 更新响应消息
          const currentMessages = getMessages() || [];
          setMessages([...currentMessages.slice(0, -1), updatedResponse]); // 更新消息状态
        }
      } else if (event === 'on_run_step_delta') {
        // 处理'on_run_step_delta'事件（步骤增量更新）
        const runStepDelta = data as Agents.RunStepDeltaEvent;
        const runStep = stepMap.current.get(runStepDelta.id);
        const responseMessageId = runStep?.runId ?? '';

        if (!runStep || !responseMessageId) {
          console.warn('No run step or runId found for run step delta event');
          return;
        }

        const response = messageMap.current.get(responseMessageId);
        if (
          response &&
          runStepDelta.delta.type === StepTypes.TOOL_CALLS &&
          runStepDelta.delta.tool_calls
        ) {
          let updatedResponse = { ...response };

          // 更新响应消息中的工具调用增量
          runStepDelta.delta.tool_calls.forEach((toolCallDelta) => {
            const toolCallId = toolCallIdMap.current.get(runStepDelta.id) ?? '';

            const contentPart: Agents.MessageContentComplex = {
              type: ContentTypes.TOOL_CALL,
              tool_call: {
                name: toolCallDelta.name ?? '',
                args: toolCallDelta.args ?? '',
                id: toolCallId,
              },
            };

            if (runStepDelta.delta.auth != null) {
              contentPart.tool_call.auth = runStepDelta.delta.auth;
              contentPart.tool_call.expires_at = runStepDelta.delta.expires_at;
            }

            updatedResponse = updateContent(updatedResponse, runStep.index, contentPart);
          });

          messageMap.current.set(responseMessageId, updatedResponse); // 更新响应消息
          const updatedMessages = messages.map((msg) =>
            msg.messageId === runStep.runId ? updatedResponse : msg,
          );

          setMessages(updatedMessages); // 更新消息状态
        }
      } else if (event === 'on_run_step_completed') {
        // 处理'on_run_step_completed'事件（工具调用完成）
        const { result } = data as unknown as { result: Agents.ToolEndEvent };

        const { id: stepId } = result;

        const runStep = stepMap.current.get(stepId);
        const responseMessageId = runStep?.runId ?? '';

        if (!runStep || !responseMessageId) {
          console.warn('No run step or runId found for completed tool call event');
          return;
        }

        const response = messageMap.current.get(responseMessageId);
        if (response) {
          let updatedResponse = { ...response };

          // 更新响应消息中的工具调用结果
          const contentPart: Agents.MessageContentComplex = {
            type: ContentTypes.TOOL_CALL,
            tool_call: result.tool_call,
          };

          updatedResponse = updateContent(updatedResponse, runStep.index, contentPart, true);

          messageMap.current.set(responseMessageId, updatedResponse); // 更新响应消息
          const updatedMessages = messages.map((msg) =>
            msg.messageId === runStep.runId ? updatedResponse : msg,
          );

          setMessages(updatedMessages); // 更新消息状态
        }
      }

      // 清理：清除存储的工具调用、消息和步骤数据
      return () => {
        toolCallIdMap.current.clear();
        messageMap.current.clear();
        stepMap.current.clear();
      };
    },
    [getMessages, setIsSubmitting, lastAnnouncementTimeRef, announcePolite, setMessages],
  );
}
