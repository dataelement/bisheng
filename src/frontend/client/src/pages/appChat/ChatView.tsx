import { useCallback, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useRecoilState, useRecoilValue } from "recoil";
import AppAvator from "~/components/Avator";
import HeaderTitle from "~/components/Chat/HeaderTitle";
import { useCitationReferencePanel } from "~/components/Chat/Messages/Content/useCitationReferencePanel";
import {
    ExportFormatSheet,
    MessageSelectionToolbar,
} from "~/components/Chat/MessageSelection";
import { useAuthContext, useLocalize } from "~/hooks";
import {
    useExitSelectionOnChatChange,
    useMessageSelection,
    type SelectableMessage,
} from "~/hooks/useMessageSelection";
import usePrefersMobileLayout from "~/hooks/usePrefersMobileLayout";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import {
    importMessagesToKnowledgeApi,
    listUploadableSpacesApi,
} from "~/api/messageExport";
import {
    AddToKnowledgeModal,
    type AddToKnowledgeSelection,
} from "~/pages/Subscription/Article/AddToKnowledgeModal";
import ChatInput from "./ChatInput";
import ChatMessages from "./ChatMessages";
import { ChatEmptyState } from "./components/ChatEmptyState";
import { copyAppChatOrigin, copyAppChatReturnTo } from "~/pages/appChat/appChatOrigin";
import { appConversationsState } from "./store/appSidebarAtoms";
import { currentChatState, currentRunningState } from "./store/atoms";
import useChatHelpers from "./useChatHelpers";
import { useWebSocket } from "./useWebsocket";
import { generateUUID } from "~/utils";

// Same selectable-category set as ChatMessages.tsx. Duplicated here because
// the toolbar's ``messages`` prop drives ``getSelectedIds`` and needs the
// same filtered, position-stable list.
const _SELECTABLE_CATEGORIES = new Set([
    "question",
    "answer",
    "agent_answer",
    "output_msg",
    "stream_msg",
]);

export default function ChatView({ data, cid, v, readOnly, isGuestMode = false }) {
    const { user } = useAuthContext();
    const help = useChatHelpers()
    useWebSocket(help)

    const localize = useLocalize();
    const navigate = useNavigate();
    const location = useLocation();
    const { fid: flowId, type: flowType } = useParams();
    const chatState = useRecoilValue(currentChatState);
    const running = useRecoilValue(currentRunningState);
    const conversations = useRecoilValue(appConversationsState);
    const [, setConversations] = useRecoilState(appConversationsState);

    // Lightweight createNewChat — avoids importing useAppSidebar which would
    // spin up a second auto-fetch/auto-select effect and overwrite placeholders.
    const createNewChat = useCallback(() => {
        if (!flowId || !flowType) return;
        const chatId = generateUUID(32);
        if (cid) copyAppChatOrigin(cid, chatId);
        if (cid) copyAppChatReturnTo(cid, chatId);
        setConversations((prev) => [{
            id: chatId,
            title: localize('com_ui_new_chat'),
            flowId: flowId,
            flowType: Number(flowType),
            updatedAt: new Date().toISOString(),
            createdAt: new Date().toISOString(),
        }, ...prev]);
        const nextPath = `/app/${chatId}/${flowId}/${flowType}`;
        navigate(nextPath, { state: location.state });
    }, [flowId, flowType, localize, location.state, navigate, setConversations, cid]);

    const messages = chatState?.messages || [];
    const hasMessages = messages.length > 0;

    // ── F028 selection mode wiring (mirrors workstation ChatView) ──
    useExitSelectionOnChatChange(cid);
    const {
        state: selectionState,
        getSelectedIds,
        exitSelectionMode,
    } = useMessageSelection();
    const isH5 = usePrefersMobileLayout();
    const { showToast } = useToastContext();
    const [exportSheetOpen, setExportSheetOpen] = useState(false);
    const [importModalOpen, setImportModalOpen] = useState(false);

    const selectableMessages = useMemo<SelectableMessage[]>(
        () =>
            messages
                .filter(
                    (m: any) => m?.id != null && _SELECTABLE_CATEGORIES.has(m?.category),
                )
                .map((m: any) => ({
                    messageId: String(m.id),
                    parentMessageId: "",
                    isCreatedByUser: m.category === "question",
                })),
        [messages],
    );

    const handleImportSelect = useCallback(
        async (selection: AddToKnowledgeSelection) => {
            if (!cid) return;
            const ids = getSelectedIds(selectableMessages);
            const messageIds = ids
                .map((s) => Number.parseInt(s, 10))
                .filter((n) => Number.isFinite(n));
            if (!messageIds.length) return;
            try {
                const resp = await importMessagesToKnowledgeApi({
                    chatId: cid,
                    messageIds,
                    knowledgeSpaceId: Number(selection.knowledgeSpaceId),
                    parentId: selection.folderId ? Number(selection.folderId) : null,
                });
                showToast({
                    message:
                        localize("workstation.messageExport.importSuccess") +
                        (resp.dup_renamed ? ` (${resp.target_filename})` : ""),
                    severity: NotificationSeverity.SUCCESS,
                });
                setImportModalOpen(false);
                exitSelectionMode();
            } catch {
                showToast({
                    message: localize("workstation.messageExport.renderFailed"),
                    severity: NotificationSeverity.ERROR,
                });
            }
        },
        [cid, selectableMessages, getSelectedIds, showToast, localize, exitSelectionMode],
    );
    const { activeCitationMessageId, citationPanelElement, onOpenCitationPanel } = useCitationReferencePanel({ hasMessages });
    const activeConversation = useMemo(
        () => conversations.find((item) => item.id === cid),
        [conversations, cid]
    );
    const headerTitle = [activeConversation?.title, data?.name]
        .map((item) => String(item || "").trim())
        .find(Boolean) || localize('com_ui_new_chat');

    /** 与侧栏「分享应用」一致：仅 can_share === true 时展示对话顶栏分享入口 */
    const hideShare = data?.can_share !== true;

    /** 无消息且无需展示开场白 / 引导问题 / 工作流表单时显示主区域空状态 */
    const showChatEmptyState =
        conversations.length === 0 &&
        messages.length === 0 &&
        !data?.guide_word &&
        !running?.inputForm &&
        !(running?.guideWord?.length);

    const Logo = useMemo(() => {
        return <AppAvator className="size-6 min-w-6" url={data.logo} id={data.name} flowType={data.flow_type} />
    }, [data]);

    return <div className="relative h-full flex flex-col">
        <div className="min-h-0 flex-1 flex flex-col bg-[position:0_100%] bg-repeat-x bg-[length:10px_432px]">
            {showChatEmptyState ? (
                <div className="flex min-h-0 flex-1 flex-col">
                    <HeaderTitle
                        readOnly={readOnly}
                        hideShare={hideShare}
                        conversation={{ title: headerTitle, flowId: data.id, conversationId: cid, flowType: data.flow_type }}
                    />
                    <ChatEmptyState onNewChat={createNewChat} />
                </div>
            ) : (
                <div className="flex min-h-0 flex-1 overflow-hidden">
                    <div className="relative flex min-w-0 flex-1 min-h-0 flex-col overflow-hidden">
                        <HeaderTitle
                            readOnly={readOnly}
                            hideShare={hideShare}
                            conversation={{ title: headerTitle, flowId: data.id, conversationId: cid, flowType: data.flow_type }}
                        />
                        <div className="flex min-h-0 flex-1 overflow-hidden">
                            <div className="relative mx-auto h-full min-h-0 w-full max-w-[800px] flex-1">
                                <ChatMessages
                                    useName={user?.username}
                                    title={data.name}
                                    logo={Logo}
                                    readOnly={readOnly}
                                    isGuestMode={isGuestMode}
                                    disabledSearch={data.flow_type === 10}
                                    onOpenCitationPanel={onOpenCitationPanel}
                                    activeCitationMessageId={activeCitationMessageId}
                                    selectionActive={!!(cid && selectionState.active && selectionState.chatId === cid)}
                                />
                            </div>
                        </div>
                        {!readOnly && (
                            cid && selectionState.active && selectionState.chatId === cid ? (
                                /* F028: input is replaced by the selection toolbar at 100% width */
                                <div className="z-10 w-full max-w-[800px] mx-auto shrink-0 bg-[#fff] dark:bg-[#1B1B1B] py-1.5">
                                    <MessageSelectionToolbar
                                        chatId={cid}
                                        messages={selectableMessages}
                                        onExportToLocal={isH5 ? () => setExportSheetOpen(true) : undefined}
                                        onImportToKnowledge={() => setImportModalOpen(true)}
                                    />
                                </div>
                            ) : (
                                <ChatInput v={v} readOnly={readOnly} />
                            )
                        )}
                    </div>

                    {citationPanelElement}
                </div>
            )}
        </div>

        {/* F028: portal-style sheets/modals (the floating toolbar lives next to the input) */}
        {cid && selectionState.active && selectionState.chatId === cid && (
            <>
                <ExportFormatSheet
                    open={exportSheetOpen}
                    onOpenChange={setExportSheetOpen}
                    chatId={cid}
                    messages={selectableMessages}
                />
                <AddToKnowledgeModal
                    open={importModalOpen}
                    onOpenChange={setImportModalOpen}
                    mode="channel_sync"
                    dataSourceApi={listUploadableSpacesApi}
                    onSyncSelect={handleImportSelect}
                />
            </>
        )}
    </div>
};
