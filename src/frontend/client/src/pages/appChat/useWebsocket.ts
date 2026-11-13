// @ts-strict-ignore
"use client";
import { useEffect, useRef, useState } from "react";
import { useRecoilState, useRecoilValue } from "recoil";
import { NotificationSeverity } from "~/common";
import { useLocalize, useToast } from "~/hooks";
import { SkillMethod } from "./appUtils/skillMethod";
import { chatApiVersionState, submitDataState } from "./store/atoms";
import { appConversationsState } from "./store/appSidebarAtoms";
import { genTitle } from "~/api/chat/data-service";
import logger from "~/utils/logger";
import { generateUUID } from "~/utils";
import { useOptionalStandaloneChatContext } from "~/pages/standaloneChat/StandaloneChatContext";
import {
  buildWorkflowInitMessage,
  claimWorkflowHandshake,
  createWorkflowActivation,
  decideWorkflowCloseAction,
  isWorkflowFinishedStatusCheck,
  syncWorkflowActivation,
} from "./workflowAutoRerun";
import type { WorkflowCloseAction } from "./workflowAutoRerun";
import { isMemoryFrame, readMemoryFrame, takeQueuedMemoryFlags } from "./appMemory";

export const AppLostMessage = "11111";
const unavailableCodes = new Set(["10421", "13002", "13010", AppLostMessage]);
const wsMap = new Map<string, WebSocket>();
// 会话运行时信息
const sessionInfoMap = new Map<string, any>();
const restartCallbacks = new Map<string, () => void>();

/**
 * Force-close the websocket and forget any session info for the given chatId.
 * Used when a conversation is deleted while streaming — without this, the
 * background websocket keeps running and writing messages into Recoil state
 * for a conversation that no longer exists, which causes the "ghost" output
 * the user sees after deleting an in-flight chat.
 */
export const closeAppChatWebSocket = (chatId: string) => {
  const ws = wsMap.get(chatId);
  if (ws) {
    try {
      // Best-effort: tell backend to stop processing before yanking the socket.
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: "stop" }));
      }
      // Detach handlers so the close event doesn't bubble error toasts.
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      ws.close();
    } catch {
      // ignore — the socket may already be in a teardown state
    }
  }
  wsMap.delete(chatId);
  sessionInfoMap.delete(chatId);
  restartCallbacks.delete(chatId);
};

export const enum ActionType {
  INIT_DATA = "init_data",
  INPUT = "input",
  CHECK_STATUS = "check_status",
  STOP = "stop",
  RESTART = "restart",
  FORM_SUBMIT = "form_submit",
  MESSAGE_INPUT = "message_input",
  SKILL_INPUT = "skill_input",
  SKILL_FORM_SUBMIT = "skill_form_submit",
}

export type AgentLongTaskStatus = {
  execution_id: string;
  local_state: string;
  remote_state: string;
  cancel_state: string;
  call_sequence?: number;
  progress?: number;
  reason?: string;
  interaction_pending?: boolean;
  interaction_status_version?: number;
  status_version?: number;
  deadline?: number;
};

export type AgentInteractionStatus = {
  execution_id: string;
  interaction_id: string;
  revision: string | null;
  phase: "WAITING_INPUT" | "SUBMIT_QUEUED" | "SUBMIT_IN_FLIGHT" | "SUBMIT_UNKNOWN" | "WAITING_RESULT" | "TERMINAL";
  status_version: number;
  expires_at: string;
  form?: { type: "text"; label: string; required: true; max_length: number };
};

type AgentAnswer = {
  execution_id: string;
  interaction_id: string;
  revision: string;
  submission_id: string;
  answer: string;
};

const CANCEL_ORDER: Record<string, number> = {
  NONE: 0, INTENT: 1, SENT: 2, ACCEPTED: 3,
  CONFIRMED: 4, REJECTED: 4, UNCONFIRMED: 4, NO_ACTION: 4,
};

export const useWebSocket = (helpers, { canExecute = true, onLongTaskStatus }: {
  canExecute?: boolean;
  onLongTaskStatus?: (chatId: string, status: AgentLongTaskStatus | null) => void;
} = {}) => {
  const { showToast } = useToast();
  const [submitData, setSubmitData] = useRecoilState(submitDataState);
  const [, setAppConversations] = useRecoilState(appConversationsState);
  const apiVersion = useRecoilValue(chatApiVersionState);
  const localize = useLocalize();
  const standaloneContext = useOptionalStandaloneChatContext();
  const activationRef = useRef(createWorkflowActivation(helpers.chatId));
  activationRef.current = syncWorkflowActivation(activationRef.current, helpers.chatId);

  const stoppedRef = useRef<Record<string, boolean>>({});
  const longTaskRef = useRef<Record<string, AgentLongTaskStatus>>({});
  const interactionRef = useRef<Record<string, AgentInteractionStatus>>({});
  const pendingAnswer = useRef<Record<string, { value: AgentAnswer; socket: WebSocket }>>({});
  const pendingStop = useRef<Record<string, { executionId: string; socket?: WebSocket }>>({});
  const blockedInteraction = useRef<Record<string, boolean>>({});
  const formAttempt = useRef<Record<string, number>>({});
  const refreshInteraction = useRef<() => void>(() => {});
  const [interactionView, setInteractionView] = useState<{ chatId: string; status?: AgentInteractionStatus }>();
  const interaction = interactionView?.chatId === helpers.chatId ? interactionView?.status : undefined;
  const unavailableRef = useRef<Record<string, string>>({});
  const isUnavailable = () =>
    unavailableCodes.has(String(helpers.appLost)) || !!unavailableRef.current[helpers.chatId];

  const websocket = wsMap.get(helpers.chatId);
  const currentChatId = useCurrentChatId(helpers.chatId);

  // Track whether genTitle has been called for this chatId to avoid duplicates
  const hasGeneratedTitleRef = useRef<Record<string, boolean>>({});

  /**
   * Generate an AI title for a new conversation after the first AI response.
   * Mirrors the logic in useAiChat.ts onFinal for daily-mode conversations.
   */
  const triggerGenTitle = () => {
    const chatId = helpers.chatId;
    if (!helpers.flow?.isNew) return;
    if (hasGeneratedTitleRef.current[chatId]) return;
    hasGeneratedTitleRef.current[chatId] = true;

    genTitle({ conversationId: chatId }, apiVersion)
      .then((res: { title?: string }) => {
        if (!res?.title) return;
        // Update the sidebar conversation list with the new title
        setAppConversations((prev) => prev.map((c) => (c.id === chatId ? { ...c, title: res.title! } : c)));
      })
      .catch(() => {
        // genTitle failure is non-critical
      });
  };

  const sendWorkflowStatusCheck = (ws: WebSocket, refresh = false) => {
    const activation = activationRef.current;
    if (!refresh && !claimWorkflowHandshake(activation, helpers.chatId)) return;
    const executionId = interactionRef.current[helpers.chatId]?.execution_id ?? longTaskRef.current[helpers.chatId]?.execution_id;

    ws.send(
      JSON.stringify({
        action: ActionType.CHECK_STATUS,
        chat_id: helpers.chatId,
        flow_id: helpers.flow.id,
        ...(executionId ? { execution_id: executionId } : {}),
      }),
    );
  };

  const sendInteractionStop = (ws: WebSocket, chatId: string) => {
    const stop = pendingStop.current[chatId];
    if (stop && stop.socket !== ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "stop", execution_id: stop.executionId }));
      stop.socket = ws;
    }
  };

  const blockInteraction = (chatId: string) => {
    delete pendingAnswer.current[chatId];
    delete pendingStop.current[chatId];
    const current = interactionRef.current[chatId];
    if (current) interactionRef.current[chatId] = { ...current, form: undefined };
    blockedInteraction.current[chatId] = true;
    setInteractionView({ chatId });
    helpers.stopShow(false);
  };

  // 连接WebSocket
  const connect = (callBack) => {
    if (!canExecute || isUnavailable() || blockedInteraction.current[helpers.chatId]) return;
    const existingSocket = wsMap.get(helpers.chatId);
    const replacingExistingSocket = !!existingSocket;
    if (existingSocket) {
      if (!callBack) {
        if (existingSocket.readyState === WebSocket.OPEN) {
          if (helpers.flow.flow_type === 10) {
            sendWorkflowStatusCheck(existingSocket);
          }
          return;
        }
        if (existingSocket.readyState === WebSocket.CONNECTING) return;
        wsMap.delete(helpers.chatId);
      } else if (existingSocket.readyState === WebSocket.OPEN) {
        return;
      }
    }
    if (!helpers.wsUrl) return;

    const isSecureProtocol = window.location.protocol === "https:";
    const webSocketProtocol = isSecureProtocol ? "wss" : "ws";
    const ws = new WebSocket(`${webSocketProtocol}://${helpers.wsUrl}`);
    wsMap.set(helpers.chatId, ws);

    ws.onopen = () => {
      if (wsMap.get(helpers.chatId) !== ws) return;
      console.log("WebSocket connection established!");
      helpers.clearError();
      if (helpers.flow.flow_type === 10) {
        // 工作流初始化
        // console.log('helpers.flow :>> ', helpers.flow);
        const shouldCheckStatus = replacingExistingSocket || !helpers.flow.isNew;
        if (shouldCheckStatus) {
          sendInteractionStop(ws, helpers.chatId);
          sendWorkflowStatusCheck(ws, replacingExistingSocket);
          return;
        }
        const { data, ...flow } = helpers.flow;
        const msg = {
          action: ActionType.INIT_DATA,
          initial_open: true,
          chat_id: helpers.chatId,
          flow_id: helpers.flow.id,
          data: { ...flow, ...data },
        };
        claimWorkflowHandshake(activationRef.current, helpers.chatId);
        ws?.send(JSON.stringify(msg));
      } else {
        // 助手初始化
        const msg = {
          chatHistory: [],
          chat_id: helpers.chatId,
          flow_id: helpers.flow.id,
          inputs: {
            data:
              helpers.flow.flow_type === 5
                ? {
                    id: helpers.flow.id,
                    chatId: helpers.chatId,
                    type: helpers.flow.flow_type,
                  }
                : undefined,
          },
          name: helpers.flow.name,
          description: helpers.flow.description,
        };
        ws?.send(JSON.stringify(msg));
        // skill hack
        if (helpers.flow.flow_type === 1 && callBack) {
          callBack?.(ws);
          callBack = null;
        }
      }
    };

    ws.onmessage = (event) => {
      if (wsMap.get(helpers.chatId) !== ws) return;
      try {
        const data = JSON.parse(event.data);
        handleMessages(data, ws);

        if (data.type === "close" && callBack) {
          callBack?.(ws);
          callBack = null;
        }
      } catch (error) {
        console.error("WebSocket message parse error:", error);
      }
    };

    ws.onclose = (event) => {
      if (wsMap.get(helpers.chatId) !== ws) return;
      const chatId = helpers.chatId;
      if (event?.code === 1008 && (interactionRef.current[chatId] || longTaskRef.current[chatId]?.interaction_pending)) {
        blockInteraction(chatId);
      }
      console.log("close chatId:>> ", helpers.chatId);
      console.error("ws close :>> ", event);
      helpers.handleMsgError({ code: "", data: null }, true);
      // todo 错误消息写入消息下面
    };

    ws.onerror = (error) => {
      if (wsMap.get(helpers.chatId) !== ws) return;
      console.error("WebSocket error", helpers.chatId, error);
      helpers.handleMsgError({
        code: isUnavailable() ? unavailableRef.current[helpers.chatId] || String(helpers.appLost) : "",
        data: null,
      });
    };
  };

  const sendAgentAnswer = (ws: WebSocket, answer: AgentAnswer) => {
    ws.send(JSON.stringify({ action: "agent_interaction_submit", chat_id: helpers.chatId, ...answer }));
    pendingAnswer.current[helpers.chatId] = { value: answer, socket: ws };
  };

  const receiveInteraction = (chatId: string, status: AgentInteractionStatus, ws: WebSocket) => {
    const previous = interactionRef.current[chatId];
    const long = longTaskRef.current[chatId];
    if (!status.execution_id || !status.interaction_id || !Number.isInteger(status.status_version) ||
        (long && long.execution_id !== status.execution_id) ||
        (previous && (previous.execution_id !== status.execution_id || previous.interaction_id !== status.interaction_id ||
          previous.status_version > status.status_version))) return;
    if (status.phase === "WAITING_INPUT" && stoppedRef.current[chatId]) return;
    const validForm = status.phase === "WAITING_INPUT" && Date.parse(status.expires_at) > Date.now() && status.form?.type === "text";
    const view = validForm ? status : { ...status, form: undefined };
    interactionRef.current[chatId] = view;
    setInteractionView({ chatId, status: view });
    if (status.phase === "TERMINAL") delete pendingStop.current[chatId];
    if (status.phase !== "TERMINAL" && !stoppedRef.current[chatId]) helpers.stopShow(true);
    const pending = pendingAnswer.current[chatId];
    if (!validForm) {
      delete pendingAnswer.current[chatId];
    } else if (pending && pending.socket !== ws && pending.value.revision === status.revision) {
      sendAgentAnswer(ws, pending.value);
    }
  };

  const handleMessages = (data, _ws) => {
    // Keep terminal availability errors stable across queued close/input frames.
    if (isUnavailable()) return;
    if (blockedInteraction.current[helpers.chatId] && data.category !== "error") return;
    if (data.category === "processing" && data.type === "info" && data.message?.agent_interaction) {
      const chatId = helpers.chatId;
      if (wsMap.get(chatId) !== _ws || data.chat_id !== chatId) return;
      receiveInteraction(chatId, data.message.agent_interaction, _ws);
      if (!data.message.agent_long_task) return;
    }
    if (data.category === "processing" && data.type === "info" && data.message?.agent_long_task) {
      const status: AgentLongTaskStatus = data.message.agent_long_task;
      const chatId = helpers.chatId;
      if (wsMap.get(chatId) !== _ws || data.chat_id !== chatId || typeof status.execution_id !== "string") return;
      const previous = longTaskRef.current[chatId];
      if (previous && previous.execution_id !== status.execution_id) return;
      if (previous?.status_version !== undefined &&
          (status.status_version === undefined || status.status_version < previous.status_version)) return;
      if (status.interaction_status_version !== undefined &&
          status.interaction_status_version < (interactionRef.current[chatId]?.status_version ?? 0)) return;
      const sequence = status.call_sequence ?? 0;
      const previousSequence = previous?.call_sequence ?? 0;
      if (sequence < previousSequence) return;
      const sameCall = sequence === previousSequence ? previous : undefined;
      const localClosed = sameCall && ["STOPPED", "TIMED_OUT", "FAILED", "SUCCEEDED"].includes(sameCall.local_state);
      const remoteClosed = sameCall && ["SUCCEEDED", "FAILED", "CANCELLED"].includes(sameCall.remote_state);
      const previousCancel = sameCall ? CANCEL_ORDER[sameCall.cancel_state] : 0;
      const cancelCurrent = previousCancel === 4
        ? sameCall?.cancel_state === status.cancel_state
        : CANCEL_ORDER[status.cancel_state] >= previousCancel;
      const progressCurrent = typeof sameCall?.progress !== "number" ||
        typeof status.progress !== "number" || status.progress >= sameCall.progress;
      const wasRunning = sameCall?.remote_state === "RUNNING" || sameCall?.remote_state === "WAITING_INPUT";
      if ((!localClosed || sameCall.local_state === status.local_state) &&
          (!remoteClosed || sameCall.remote_state === status.remote_state) &&
          (!wasRunning || !["NOT_SENT", "START_IN_FLIGHT", "START_UNKNOWN", "QUEUED"].includes(status.remote_state)) &&
          cancelCurrent && progressCurrent) {
        longTaskRef.current[chatId] = status;
        onLongTaskStatus?.(chatId, status);
        if (status.status_version !== undefined) {
          const finished = ["STOPPED", "TIMED_OUT", "FAILED", "SUCCEEDED"].includes(status.local_state);
          if (finished) delete pendingStop.current[chatId];
          if (status.local_state === "SUCCEEDED") stoppedRef.current[chatId] = false;
          helpers.stopShow(!finished && !stoppedRef.current[chatId]);
        }
        if (interactionRef.current[chatId] && ["STOPPED", "TIMED_OUT", "FAILED"].includes(status.local_state)) {
          helpers.stopShow(false);
        }
        if (status.interaction_pending && !data.message.agent_interaction &&
            !interactionRef.current[chatId] && !stoppedRef.current[chatId]) sendWorkflowStatusCheck(_ws, true);
      }
      return;
    }
    // F132: memory signal — pin it on the answer (assistant only); never a chat row itself.
    if (isMemoryFrame(data)) {
      const memory = readMemoryFrame(data);
      if (memory && helpers.flow.flow_type !== 10) {
        helpers.message.attachMemory(helpers.chatId, memory.flags, memory.messageId);
      }
      return;
    }
    // 过滤无效数据
    if (data.category === "end_cover" && data.type !== "end_cover") {
      return;
    }

    const resumedExecution = data.message?.agent_long_task_execution_id;
    if (resumedExecution && (data.chat_id !== helpers.chatId ||
        resumedExecution !== longTaskRef.current[helpers.chatId]?.execution_id)) return;

    // Freeze partial output after a manual stop; only terminal IDs and errors may follow.
    const stopped = stoppedRef.current[helpers.chatId] === true;
    if (stopped && !(data.category === "processing" && data.type === "close")
      && data.category !== "error" && data.type !== "error") {
      helpers.message.finishStoppedMsg(helpers.chatId, data);
      return;
    }

    let workflowCloseAction: WorkflowCloseAction | null = null;
    if (helpers.flow.flow_type === 10 && data.type === "close" && data.category === "processing") {
      workflowCloseAction = stopped ? "manual" : decideWorkflowCloseAction({
        data,
        activation: activationRef.current,
        enabled: standaloneContext?.autoRerunOnOpen ?? false,
        isStandaloneWorkflow: standaloneContext?.flowType === "workflow",
        isNewConversation: !!helpers.flow.isNew,
      });
      logger.debug("workflow-auto-rerun", {
        chatId: helpers.chatId,
        decision: workflowCloseAction,
      });
      if (workflowCloseAction === "ignore") return;
      if (isWorkflowFinishedStatusCheck(data)) {
        activationRef.current.handled = true;
      }
    }

    if (data.type === "begin") {
      // 工作流input会有再begin之前出现的情况
      // helpers.stopShow(true)
    } else if (data.type === "close" && data.category === "processing") {
      helpers.stopShow(false);
      helpers.message.closeAllLogMsg(helpers.chatId);
      // Generate title for new conversations after first round completes
      // triggerGenTitle()
    }

    // messages
    if (data.category === "error" || data.type === "error") {
      if (data.message?.agent_interaction_error) {
        const chatId = helpers.chatId;
        const current = interactionRef.current[chatId];
        const long = longTaskRef.current[chatId];
        const executionId = current?.execution_id ?? long?.execution_id;
        if (data.chat_id !== chatId ||
            (data.message.execution_id && executionId && data.message.execution_id !== executionId)) return;
        if (data.message.agent_interaction_error === "retry" && stoppedRef.current[chatId]) return;
        if (data.message.agent_interaction_error === "retry" && current) {
          delete pendingAnswer.current[chatId];
          formAttempt.current[chatId] = (formAttempt.current[chatId] ?? 0) + 1;
          const status = { ...current, form: undefined };
          interactionRef.current[chatId] = status;
          setInteractionView({ chatId, status });
          sendWorkflowStatusCheck(_ws, true);
        } else {
          blockInteraction(chatId);
          if (long?.status_version !== undefined) {
            delete longTaskRef.current[chatId];
            onLongTaskStatus?.(chatId, null);
          }
        }
      }
      let code = 0,
        message = "";
      if (typeof data.message === "string") {
        // 兼容助手错误信息
        const _data = JSON.parse(data.message);
        code = _data.status_code;
        message = _data.status_message;
      } else {
        code = data.message.status_code;
        message = data.message.status_message;
      }
      if (unavailableCodes.has(String(code))) {
        unavailableRef.current[helpers.chatId] = String(code);
        restartCallbacks.delete(helpers.chatId);
        sessionInfoMap.delete(helpers.chatId);
        helpers.handleMsgError({ code: String(code), data: data.message?.data });
        helpers.message.closeAllLogMsg(helpers.chatId);
      }
      if (![10421, 13002].includes(code)) {
        showToast({
          message:
            code === 500
              ? message
              : localize(`api_errors.${String(code)}`, {
                  ...(data.message?.data || {}),
                  defaultValue: localize("api_errors.fallback"),
                }),
          severity: NotificationSeverity.WARNING,
        });
      }
      return helpers.message.closeAllMsg(helpers.chatId);
    } else if (data.category === "node_run") {
      return helpers.message.createNodeMsg(helpers.chatId, data);
    } else if (data.category === "guide_word") {
      data.message.msg = data.message.guide_word;
    } else if (data.category === "input") {
      const { node_id, input_schema } = data.message;
      sessionInfoMap.set(helpers.chatId, { node_id, message_id: data.message_id });
      // 待用户输入
      helpers.showInputForm({ ...input_schema, node_id });
      return;
    } else if (data.category === "guide_question") {
      return helpers.showGuideQuestion(
        helpers.chatId,
        data.message.guide_question.filter((q) => q),
      );
    } else if (data.category === "stream_msg") {
      // helpers.flow.flow_type === 10 && helpers.reRunShow(true) // 成环的工作流不展示重跑按钮
      helpers.message.streamMsg(helpers.chatId, data);
      if (data.type === "end") triggerGenTitle();
    } else if (data.category === "end_cover" && data.type === "end_cover") {
      _ws.send(JSON.stringify({ action: "stop" }));
      return helpers.message.endMsg(helpers.chatId, data);
    }

    /***** 技能 & 助手 start******/
    if (helpers.flow.flow_type !== 10) {
      if (Array.isArray(data) && data.length) return;
      if (data.type === "start") {
        const _data = helpers.flow.flow_type === 5 ? data : SkillMethod.getStartParam(data, helpers.chatId);
        helpers.message.createMsg(helpers.chatId, _data);
      } else if (data.type === "stream") {
        helpers.message.skillStreamMsg(helpers.chatId, data);
      }
      if (["end", "end_cover"].includes(data.type) && data.receiver?.is_self) {
        // 群聊@自己时
        helpers.showInputForm({});
      } else if (["end", "end_cover"].includes(data.type)) {
        // todo 无未闭合的消息，先创建（补一条start）  工具类除外
        helpers.message.skillStreamMsg(helpers.chatId, data);
      } else if (data.type === "close") {
        helpers.message.skillCloseMsg();
        // Generate title for new conversations after first round completes
        // triggerGenTitle()
      }
      // F132: a memory signal that beat its answer row lands once the round ends.
      if (["end", "end_cover", "close"].includes(data.type)) {
        const queued = takeQueuedMemoryFlags(helpers.chatId);
        if (queued) helpers.message.attachMemory(helpers.chatId, queued);
      }

      return;
    }
    /***** 技能 end******/
    if (data.type === "close" && data.category === "processing") {
      if (!stopped) helpers.message.insetSeparator(helpers.chatId, "com_chat_round_finished");
      // 重启会话按钮,接收close确认后端处理结束后重启会话
      const restartCallback = restartCallbacks.get(helpers.chatId);
      if (restartCallback) {
        restartCallbacks.delete(helpers.chatId);
        restartCallback();
      } else {
        if (workflowCloseAction === "auto") {
          helpers.reRunShow(false);
          helpers.stopShow(true);
          _ws.send(JSON.stringify(buildWorkflowInitMessage(helpers.flow, helpers.chatId)));
        } else if (workflowCloseAction === "manual") {
          helpers.reRunShow(true);
        }
      }
    } else if (data.type === "over") {
      helpers.message.createMsg(helpers.chatId, data);
    }
  };
  useEffect(() => {
    if (!canExecute) return;
    connect();

    return () => {
      // 后台运行的会话结束后，断开WebSocket连接
      if (currentChatId !== helpers.chatId) {
        // 断开WebSocket连接
        if (websocket && !helpers.running) {
          console.log("ws close", currentChatId, helpers.chatId);
          websocket.close();
          wsMap.delete(helpers.chatId);
          restartCallbacks.delete(helpers.chatId);
        }
      }
    };
  }, [helpers.chatId, helpers.running, canExecute]);

  const sendWsMsg = async (msg) => {
    if (!canExecute) return;
    if (msg.action === ActionType.INIT_DATA) {
      delete longTaskRef.current[helpers.chatId];
      delete interactionRef.current[helpers.chatId];
      delete pendingAnswer.current[helpers.chatId];
      delete pendingStop.current[helpers.chatId];
      delete blockedInteraction.current[helpers.chatId];
      delete formAttempt.current[helpers.chatId];
      setInteractionView({ chatId: helpers.chatId });
      onLongTaskStatus?.(helpers.chatId, null);
    }
    try {
      if (websocket && websocket.readyState === WebSocket.OPEN) {
        websocket.send(JSON.stringify(msg));
      } else {
        connect((_websocket) => {
          _websocket.send(JSON.stringify(msg));
        });
      }
    } catch (error: any) {
      showToast({
        message: error.message,
        severity: NotificationSeverity.WARNING,
      });
    }
  };

  const longStatus = longTaskRef.current[helpers.chatId];
  const cancelPending = ["INTENT", "SENT", "ACCEPTED"].includes(longStatus?.cancel_state ?? "");
  const pollingAgent = (!!interaction && (interaction.phase !== "TERMINAL" || cancelPending ||
    !!pendingStop.current[helpers.chatId])) ||
    (longStatus?.status_version !== undefined && (longStatus.local_state === "WAITING_RESULT" || cancelPending));
  refreshInteraction.current = () => {
    const chatId = helpers.chatId;
    if (blockedInteraction.current[chatId]) return;
    const latest = interactionRef.current[chatId];
    if (latest?.form && Date.parse(latest.expires_at) <= Date.now()) {
      const status = { ...latest, form: undefined };
      interactionRef.current[chatId] = status;
      delete pendingAnswer.current[chatId];
      setInteractionView({ chatId, status });
    }
    const socket = wsMap.get(chatId);
    if (socket?.readyState === WebSocket.OPEN) {
      sendInteractionStop(socket, chatId);
      sendWorkflowStatusCheck(socket, true);
    }
    else connect();
  };
  useEffect(() => {
    if (!canExecute || !pollingAgent) return;
    const timer = window.setInterval(() => refreshInteraction.current(), 1000);
    return () => window.clearInterval(timer);
  }, [canExecute, helpers.chatId, pollingAgent]);

  const submitInteraction = (answer: string) => {
    const chatId = helpers.chatId;
    const current = interactionRef.current[chatId];
    const ws = wsMap.get(chatId);
    if (!canExecute || blockedInteraction.current[chatId] || stoppedRef.current[chatId] || !current?.form || !current.revision ||
        Date.parse(current.expires_at) <= Date.now() || !answer.trim() ||
        Array.from(answer).length > current.form.max_length || ws?.readyState !== WebSocket.OPEN) {
      throw new Error("agent interaction is not available");
    }
    const previous = pendingAnswer.current[chatId]?.value;
    const submissionId = previous?.revision === current.revision && previous.answer === answer
      ? previous.submission_id : generateUUID(32);
    sendAgentAnswer(ws, { execution_id: current.execution_id, interaction_id: current.interaction_id,
      revision: current.revision, submission_id: submissionId, answer });
  };

  // 监听submitData变化，发送消息（必须在当前会话调用）
  useEffect(() => {
    if (submitData && isUnavailable()) {
      helpers.handleMsgError({
        code: unavailableRef.current[helpers.chatId] || String(helpers.appLost),
        data: null,
      });
      setSubmitData(null);
      return;
    }
    const chatId = helpers.chatId;
    const current = interactionRef.current[chatId];
    const long = longTaskRef.current[chatId];
    const executionId = current?.execution_id ?? (long?.status_version !== undefined ? long.execution_id : undefined);
    if (canExecute && submitData?.action === ActionType.STOP && executionId && !blockedInteraction.current[chatId]) {
      stoppedRef.current[chatId] = true;
      helpers.message.stopMsg(chatId);
      if (current) {
        const status = { ...current, form: undefined };
        interactionRef.current[chatId] = status;
        delete pendingAnswer.current[chatId];
        setInteractionView({ chatId, status });
      }
      pendingStop.current[chatId] = { executionId };
      const socket = wsMap.get(chatId);
      if (socket) sendInteractionStop(socket, chatId);
      setSubmitData(null);
      return;
    }
    if (
      canExecute &&
      submitData &&
      (submitData.action === "skill_input" || (websocket && websocket.readyState === WebSocket.OPEN))
    ) {
      const action = submitData.action;
      if (action !== ActionType.STOP) stoppedRef.current[helpers.chatId] = false;

      switch (action) {
        case ActionType.RESTART: {
          sendWsMsg({ action: "stop" });
          const initMessage = buildWorkflowInitMessage(submitData.flow, submitData.chatId);
          restartCallbacks.set(submitData.chatId, () => {
            sendWsMsg(initMessage);
          });
          break;
        }
        case ActionType.INPUT: {
          const sessionInfo = sessionInfoMap.get(helpers.chatId);
          const node = submitData.flow.data.nodes.find((node) => node.id === sessionInfo?.node_id);
          const tab = node.data.tab.value;
          let variable = "";
          node.data.group_params.some((group) =>
            group.params.some((param) => {
              if (param.tab === tab) {
                variable = param.key;
                return true;
              }
              return false;
            }),
          );

          let message = submitData.input;
          let filePath = [];
          // 文件拼接入消息
          if (submitData.files?.length) {
            const [_filePath, fileNames] = submitData.files.reduce(
              (acc, cur) => {
                acc[0].push(cur.filepath ?? cur.file_path ?? cur.path);
                acc[1].push(cur.name);
                return acc;
              },
              [[], []],
            );
            filePath = _filePath;
            // 文件拼接入消息
            const _value = submitData.input;
            message = fileNames.length > 0 ? fileNames.join("\n") + "\n" + _value : _value;
          }

          // Attachments travel twice on purpose: `dialog_files_content`
          // is what the workflow node reads, while `files` keeps them
          // as structured data so the message can render them (and the
          // backend can make them permanent) instead of relying on the
          // filenames glued onto the text.
          const messageFiles = (submitData.files || []).map((f) => ({
            file_id: f.file_id ?? f.id,
            file_name: f.name ?? f.file_name,
            file_url: f.filepath ?? f.file_path ?? f.path,
            // What the media chip draws with. Mapping down to the
            // three fields above dropped these, so a video sent from
            // a workflow rendered as a bare extension card while the
            // same file in daily chat showed its poster and length.
            ...(f.cover_filepath ? { cover_filepath: f.cover_filepath } : {}),
            ...(f.mediaDurationSec != null ? { mediaDurationSec: f.mediaDurationSec } : {}),
          }));

          sendWsMsg({
            action: "input",
            chat_id: submitData.chatId,
            flow_id: submitData.flow.id,
            data: {
              [sessionInfo?.node_id]: {
                data: {
                  [variable]: message,
                  dialog_files_content: filePath,
                },
                message,
                files: messageFiles,
                message_id: sessionInfo.message_id,
                category: "question",
                extra: "",
                source: 0,
              },
            },
          });

          helpers.message.createSendMsg(message, messageFiles);
          break;
        }
        case ActionType.SKILL_INPUT:
          sendWsMsg(submitData.data);
          helpers.message.createSendMsg(submitData.input);
          break;
        case ActionType.FORM_SUBMIT:
          sendWsMsg({
            action: "input",
            chat_id: submitData.chatId,
            flow_id: submitData.flowId,
            data: {
              [submitData.nodeId!]: {
                data: submitData.data,
                message: submitData.input,
                message_id: sessionInfoMap.get(helpers.chatId).message_id,
                category: "question",
                extra: "",
                source: 0,
              },
            },
          });

          helpers.message.createSendMsg(submitData.input);
          break;
        case ActionType.SKILL_FORM_SUBMIT:
          sendWsMsg(submitData.data);

          helpers.message.createSendMsg(submitData.input);
          break;
        case ActionType.MESSAGE_INPUT:
          sendWsMsg({
            action: "input",
            chat_id: submitData.chatId,
            flow_id: submitData.flowId,
            data: {
              [submitData.data.nodeId!]: {
                data: submitData.data.data,
                message: submitData.data.message,
                message_id: submitData.data.msgId,
              },
            },
          });
          // 闭合所有输出节点
          helpers.message.closeOutputMsg(submitData.data.data.output_result);
          break;
        case ActionType.STOP:
          stoppedRef.current[helpers.chatId] = true;
          helpers.message.stopMsg(helpers.chatId);
          sendWsMsg({ action: "stop" });
          break;
      }
      setSubmitData(null);
    }
  }, [submitData]);
  return {
    interaction,
    interactionFormKey: interaction && `${interaction.interaction_id}:${formAttempt.current[helpers.chatId] ?? 0}`,
    submitInteraction,
  };
};

const useCurrentChatId = (chatId) => {
  const currentChatIdRef = useRef<string | null>(null);
  useEffect(() => {
    currentChatIdRef.current = chatId;
  }, [chatId]);

  return currentChatIdRef.current;
};
