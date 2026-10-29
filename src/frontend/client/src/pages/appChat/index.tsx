// @ts-strict-ignore
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useRecoilState, useRecoilValue, useSetRecoilState } from "recoil";
import { ChatMessageType, FlowData } from "~/@types/chat";
import { getAssistantDetailApi, getChatHistoryApi, getFlowApi, postBuildInit } from "~/api/apps";
import { checkResourceAction } from "~/api/permission";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { useLocalize } from "~/hooks";
import store from "~/store";
import ChatView from "./ChatView";
import { appConversationsState } from "./store/appSidebarAtoms";
import {
  chatApiVersionState,
  chatIdState,
  chatsState,
  currentChatState,
  runningState,
  tabsState,
} from "./store/atoms";
import { showApiError } from "~/api/request";
import { Button } from "@bisheng/ui";

const API_VERSION = "v1";
export const enum FLOW_TYPES {
  WORK_FLOW = 10,
  ASSISTANT = 5,
  SKILL = 1,
}

export default function AppChat({
  chatId = "",
  flowId = "",
  shareToken = "",
  flowType = "",
  apiVersion = "",
  isGuestMode = false,
}) {
  const { conversationId: _cid, fid: _fid, type: _type } = useParams();
  const cid = _cid || chatId;
  const fid = _fid || flowId;
  const type = _type || flowType;
  const effectiveApiVersion = apiVersion || API_VERSION;
  const [readOnly] = useState(shareToken);
  const setApiVersion = useRecoilState(chatApiVersionState)[1];

  // Sync apiVersion so the chat helpers use the selected channel's WS URLs.
  useEffect(() => {
    setApiVersion(effectiveApiVersion as "v1" | "v2" | "v3");
    return () => {
      setApiVersion("v1");
    };
  }, [effectiveApiVersion, setApiVersion]);
  const [chats, setChats] = useRecoilState(chatsState);
  const [, setRunningState] = useRecoilState(runningState);
  const [, setChatId] = useRecoilState(chatIdState);
  const chatState = useRecoilValue(currentChatState);
  const conversations = useRecoilValue(appConversationsState);
  const setChatMobileHeader = useSetRecoilState(store.chatMobileHeaderState);
  const localize = useLocalize();
  const build = useBuild();
  const navigate = useNavigate();
  const { showToast } = useToastContext();
  const [loadError, setLoadError] = useState<unknown>(null);

  const flow = chatState?.flow;
  const headerTitleForMobile = useMemo(() => {
    if (!cid) return localize("com_ui_new_chat");
    const activeConversation = conversations.find((item) => item.id === cid);
    return (
      [activeConversation?.title, flow?.name].map((item) => String(item || "").trim()).find(Boolean) ||
      localize("com_ui_new_chat")
    );
  }, [cid, conversations, flow?.name, localize]);

  const hideShareForMobile = flow?.can_share !== true;

  // MobileNav still needs the shared header title before the flow reaches Recoil and mounts ChatView.
  useEffect(() => {
    if (!cid || !fid || !type) return;
    setChatMobileHeader({
      title: headerTitleForMobile,
      conversationId: cid,
      flowId: flow?.id || String(fid),
      flowType: Number(flow?.flow_type ?? type) || 15,
      readOnly: !!readOnly,
      hideShare: hideShareForMobile,
    });
    return () => setChatMobileHeader(null);
  }, [
    cid,
    fid,
    type,
    flow?.id,
    flow?.flow_type,
    headerTitleForMobile,
    readOnly,
    hideShareForMobile,
    setChatMobileHeader,
  ]);

  // console.log('[chatState] :>> ', chatState);
  // console.log('[runningState] :>> ', __);
  // Switch the active conversation.
  const init = async () => {
    if (!cid) return;
    setLoadError(null);

    let flowData: FlowData | null = null;
    let messages: ChatMessageType[] = [];
    const currentData = chats[cid];
    let error: { code: string; data: any } = { code: "", data: null };

    setChatId(cid!); // Switch the active conversation.

    const numericType = Number(type);
    const ensureUseAppPermission = async (objectType: "workflow" | "assistant") => {
      if (shareToken || isGuestMode) return true;
      const permission = await checkResourceAction({
        resource_type: objectType,
        resource_id: fid!,
        action: "use",
      });
      if (permission?.allowed) return true;
      showToast?.({
        message: localize("com_plugin_feature_no_access_toast"),
        severity: NotificationSeverity.WARNING,
      });
      navigate("/apps", { replace: true });
      return false;
    };

    if (numericType === FLOW_TYPES.WORK_FLOW && !(await ensureUseAppPermission("workflow"))) return;
    if (numericType === FLOW_TYPES.ASSISTANT && !(await ensureUseAppPermission("assistant"))) return;

    if (currentData) {
      // Do not reload a cached conversation.
      numericType === FLOW_TYPES.SKILL &&
        setRunningState((prev) => {
          // Reset the input state for a skill conversation.
          return {
            ...prev,
            [cid]: {
              ...(prev?.[cid] || {}),
              inputDisabled: false,
            },
          };
        });
      return;
    }

    switch (numericType) {
      case FLOW_TYPES.SKILL:
        // Skill (flow_type=1) is not accessible via app chat — redirect to 404
        navigate("/404", { replace: true });
        return;
      case FLOW_TYPES.WORK_FLOW:
        // Fetch detail and chat history, skip global 403 redirect
        const [flowRes, msgRes] = await Promise.all([
          getFlowApi(fid!, effectiveApiVersion, shareToken, true),
          getChatHistoryApi({
            flowId: fid,
            chatId: cid,
            flowType: type,
            shareToken,
            apiVersion: effectiveApiVersion,
          }),
        ]);

        messages = msgRes.reverse();
        flowData = { ...flowRes.data, isNew: !messages.length };

        if (numericType === FLOW_TYPES.SKILL) {
          try {
            await build(flowData, cid);
          } catch {}
        }
        break;
      case FLOW_TYPES.ASSISTANT:
        // Fetch assistant detail, skip global 403 redirect
        const [assistantRes, historyRes] = await Promise.all([
          getAssistantDetailApi(fid, shareToken, true, effectiveApiVersion),
          getChatHistoryApi({
            flowId: fid,
            chatId: cid,
            flowType: type,
            shareToken,
            apiVersion: effectiveApiVersion,
          }),
        ]);

        messages = historyRes.reverse();
        flowData = { ...assistantRes.data, flow_type: FLOW_TYPES.ASSISTANT, isNew: !messages.length };
        break;
      default:
    }

    setChats((prevChats) => ({
      ...prevChats,
      [cid]: {
        flow: flowData,
        messages,
        historyEnd: false,
      },
    }));

    if (shareToken) {
      error = { code: "", data: null };
    }
    // Update the current conversation state.
    // !!flow.data?.nodes.find(node => ["VariableNode", "InputFileNode"].includes(node.data.type))
    setRunningState((prev) => {
      return {
        ...prev,
        [cid]: {
          running: false,
          inputDisabled: error.code || numericType === FLOW_TYPES.WORK_FLOW,
          error,
          inputForm: numericType !== FLOW_TYPES.WORK_FLOW || null,
          showUpload: numericType === FLOW_TYPES.WORK_FLOW,
          showStop: false,
          guideWord: flowData?.guide_question,
          showReRun: false,
        },
      };
    });
  };

  const handleInit = () => {
    void init().catch((cause) => {
      setLoadError(cause);
      showApiError(cause);
    });
  };
  useEffect(() => {
    handleInit();
  }, [cid]);

  if (loadError)
    return (
      <div role="alert">
        <p>{loadError instanceof Error ? loadError.message : localize("com_ui_error")}</p>
        <Button variant="outlined" onClick={handleInit}>
          {localize("com_ui_retry")}
        </Button>
      </div>
    );

  if (!cid || !chatState?.flow) return null;

  return (
    <ChatView
      data={chatState.flow}
      cid={cid}
      v={effectiveApiVersion}
      readOnly={readOnly}
      isGuestMode={isGuestMode}
    />
  );
}

/**
 * build flow
 * Validate each node, show its progress, and close the stream on end_of_stream.
 * Persist input_keys into the flow tab's formKeysData state.
 */

const useBuild = () => {
  const [, setTabsState] = useRecoilState(tabsState);

  // Consume the server-sent validation stream.
  async function streamNodeData(flow: any, chatId: string) {
    // Step 1: Make a POST request to send the flow data and receive a unique session ID
    const res = await postBuildInit({ flow, chatId });
    const flowId = res.data.flowId;
    // Step 2: Use the session ID to establish an SSE connection using EventSource
    let validationResults = [];
    let finished = false;
    let buildEnd = false;
    const apiUrl = `${__APP_ENV__.BASE_URL}/api/v1/build/stream/${flowId}?chat_id=${chatId}`;
    const eventSource = new EventSource(apiUrl);

    eventSource.onmessage = (event) => {
      // If the event is parseable, return
      if (!event.data) {
        return;
      }
      const parsedData = JSON.parse(event.data);
      // if the event is the end of the stream, close the connection
      if (parsedData.end_of_stream) {
        eventSource.close(); // Close the completed stream.
        buildEnd = true;
        return;
      } else if (parsedData.log) {
        // If the event is a log, log it
        // setSuccessData({ title: parsedData.log });
      } else if (parsedData.input_keys) {
        setTabsState((old) => {
          return {
            ...old,
            [flowId]: {
              ...old[flowId],
              formKeysData: parsedData,
            },
          };
        });
      } else {
        // setProgress(parsedData.progress);
        validationResults.push(parsedData.valid);
      }
    };

    eventSource.onerror = (error: any) => {
      buildEnd = true;
      console.error("EventSource failed:", error);
      eventSource.close();
      // if (error.data) {
      //     const parsedData = JSON.parse(error.data);
      //     showToast({ message: parsedData.error, status: 'warning' });
      // }
    };
    // Step 3: Wait for the stream to finish
    while (!finished) {
      await new Promise((resolve) => setTimeout(resolve, 100));
      finished = buildEnd; // validationResults.length === flow.data.nodes.length;
    }
    // Step 4: Return true if all nodes are valid, false otherwise
    return validationResults.every((result) => result);
  }

  // Enforce the minimum loading duration.
  async function enforceMinimumLoadingTime(startTime: number, minimumLoadingTime: number) {
    const elapsedTime = Date.now() - startTime;
    const remainingTime = minimumLoadingTime - elapsedTime;

    if (remainingTime > 0) {
      return new Promise((resolve) => setTimeout(resolve, remainingTime));
    }
  }

  async function handleBuild(flow: any, chatId: string) {
    try {
      // const errors = flow.data.nodes.flatMap((n) => validateNode(n, flow.data.edges))
      // if (errors.length > 0) {
      //     return showToast({ message: errors.join('\n'), status: 'warning' });
      // }

      const minimumLoadingTime = 200; // in milliseconds
      const startTime = Date.now();

      await streamNodeData(flow, chatId);
      await enforceMinimumLoadingTime(startTime, minimumLoadingTime);
    } catch (error) {
      console.error("Error:", error);
    } finally {
    }
  }

  return handleBuild;
};
