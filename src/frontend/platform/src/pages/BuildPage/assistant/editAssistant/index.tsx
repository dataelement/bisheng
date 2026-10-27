// @ts-strict-ignore
import { MessageStoreProvider as AssistantMessageStoreProvider } from '@/components/bs-comp/chatComponent/messageStore';
import { Button, toast } from '@bisheng/ui';
import ApiMainPage from "@/components/bs-comp/apiComponent";
import { useMessageStore } from "@/components/bs-comp/chatComponent/messageStore";
import { hasResourceAction, useResourceActions } from "@/components/bs-comp/permission/useResourceActions";

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { changeAssistantStatusApi, getAssistantDetailApi, saveAssistanttApi } from "@/controllers/API/assistant";
import { checkAppEditPermission } from "@/controllers/API/flow";
import { handleUiRequest, showApiError } from "@/controllers/request";
import { useAssistantStore } from "@/store/assistantStore";
import { OnlineState } from "@/types/flow";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router-dom";
import { useBlocker, useNavigate, useParams } from "react-router-dom";
import Header from "./Header";
import Prompt from "./Prompt";
import Setting from "./Setting";
import TestChat from "./TestChat";
import { useAutoDescription } from "./useAutoDescription";

function EditAssistantContent() {
    const { t } = useTranslation()
    const { id: assisId } = useParams()
    const navigate = useNavigate()
    const { state } = useLocation();
    const loca = state?.flow; // Get the passed flow data

    // assistant data
    const { assistantState, changed, setAssistantDetail, changeStatus, saveAfter, destroy } = useAssistantStore()
    const { startNewRound, insetSystemMsg, insetBsMsg, destory, setShowGuideQuestion } = useMessageStore()
    const [checking, setChecking] = useState(true)
    const assistantId = assisId ? String(assisId) : ''
    const { actions } = useResourceActions('assistant', assistantId ? [assistantId] : [], ['edit'])
    const canEdit = assistantId ? hasResourceAction(actions, assistantId, 'edit') : false
    // Read once on mount: Prompt clears this flag after it opens the optimization dialog
    const isNewRef = useRef(Boolean(window.assistantCreate))
    useAutoDescription(isNewRef.current && canEdit && !checking)

    const flowInit = async () => {
        await checkAppEditPermission(assisId, 5)

        await getAssistantDetailApi(assisId, 'v1').then((res) => {
            setAssistantDetail(res)
            setChecking(false)
            setShowGuideQuestion(true)
            setGuideQuestion(res.guide_question?.filter((item) => item) || [])
            res.guide_word && insetBsMsg(res.guide_word)
        })
    }

    useEffect(() => {
        void flowInit().catch(showApiError).finally(() => setChecking(false))
    }, [])

    // Store displayed guide words independently
    const [guideQuestion, setGuideQuestion] = useState([])
    const [openChat, setOpenChat] = useState(true)
    const handleStartChat = async (save) => {
        if (!handleCheck()) return
        if (save && !canEdit) return
        destory()
        setOpenChat(false)
        try {
        save ? await handleSave(true) : await new Promise((resolve) => setTimeout(resolve, 0))
        saveAfter()
        startNewRound(t('build.configurationUpdated'))
        setGuideQuestion(assistantState.guide_question.filter((item) => item))
        assistantState.guide_word && insetBsMsg(assistantState.guide_word)
        } finally {
            setOpenChat(true)
        }
    }


    // Save assistant details
    const handleSave = async (showMessage = false) => {
        if (!canEdit) return
        if (!handleCheck()) return
        await saveAssistanttApi({
            ...assistantState,
            flow_list: assistantState.flow_list.map(item => item.id),
            tool_list: assistantState.tool_list.map(item => item.id),
            knowledge_list: assistantState.knowledge_list.map(item => item.id),
            guide_question: assistantState.guide_question.filter((item) => item),
            logo: assistantState.viewLogo ? assistantState.logo : '',
        }).then(res => {
            if (!res) return
            showMessage && toast.show({ type: 'success', message: [String(t('prompt') ?? ''), String(t('skills.saveSuccessful') ?? '')].filter(Boolean).join('\n') })
        })
        saveAfter()
    }

    // Publish assistant online
    const handleOnline = async (online) => {
        if (!handleCheck()) return
        if (online) {
            await handleSave()
            await changeAssistantStatusApi(assistantState.id, 2).then(() => {
                toast.show({ type: 'success', message: [String(t('prompt') ?? ''), String(t('skills.onlineSuccessful') ?? '')].filter(Boolean).join('\n') })
            })
            setTimeout(() => {
                navigate('/build')
            }, 1200);
        } else {
            await changeAssistantStatusApi(assistantState.id, 1).then(() => {
                changeStatus(1)
            })
        }
    }

    // Validate assistant data
    const handleCheck = () => {
        const errors = []
        if (
            assistantState.max_token === undefined ||
            !Number.isInteger(assistantState.max_token) ||
            assistantState.max_token < 0 ||
            assistantState.max_token > 100 * 10000
        ) {
            errors.push(t('skills.chatHistoryMaxToken'));
        }
        if (!assistantState.model_name) {
            errors.push(t('build.modelRequired'))
        }
        if (assistantState.guide_question.some(que => que.length > 50)) {
            errors.push(t('skills.guideQuestions50'))
        }
        if (assistantState.guide_word.length > 1000) {
            errors.push(t('skills.promptWords1000'))
        }

        if (errors.length) {
            toast.show({ type: 'error', message: [String(t('prompt') ?? ''), errors.filter(Boolean).join('\n')].filter(Boolean).join('\n') })
            return false
        }
        return true
    }

    // Cleanup
    useEffect(() => {
        return destroy
    }, [])

    const [showApiPage, setShowApiPage] = useState(false)
    // Save on leave
    const blocker = useBeforeUnload(changed, checking)
    const handleSaveAndClose = async () => {
        if (!canEdit) return blocker.reset?.()
        await handleSave(true)
        blocker.proceed?.()
    }

    if (checking) return null

    return <div className="bg-background-main">
        <Header loca={loca} canEdit={canEdit} onSave={handleUiRequest(() => handleSave(true))} onLine={handleUiRequest(handleOnline)} onTabChange={(t) => setShowApiPage(t === 'api')}></Header>
        <div className="h-[calc(100vh-70px-var(--license-banner-h,0px))]">
            <div className={`flex h-full ${showApiPage ? 'hidden' : ''}`}>
                <div className="w-[60%]">
                    <div className="text-md font-medium leading-none p-4 shadow-sm">{t('build.assistantConfiguration')}</div>
                    <div className="flex h-[calc(100vh-120px-var(--license-banner-h,0px))]">
                        <Prompt canEdit={canEdit}></Prompt>
                        <Setting></Setting>
                    </div>
                </div>
                <div className="w-[40%] h-full bg-[#fff] dark:bg-background-main relative">
                    {openChat && <TestChat guideQuestion={guideQuestion} assisId={assisId} onClear={handleUiRequest(() => handleStartChat(false))}></TestChat>}
                    {/* Mask button triggered by changes to save */}
                    {changed && <div className="absolute w-full bottom-0 h-60" onClick={handleUiRequest(() => handleStartChat(true))}></div>}
                </div>
            </div>
            <div className={`h-full ${showApiPage ? '' : 'hidden'}`}>
                <ApiMainPage />
            </div>
        </div>
        <Dialog open={blocker.state === "blocked"}>
            <DialogContent className="sm:max-w-[425px]" close={false}>
                <DialogHeader>
                    <DialogTitle>{t('prompt')}</DialogTitle>
                    <DialogDescription>{assistantState.status === OnlineState.OnLine ? t('build.assistantOnlineNoEdit') : t('build.unsavedChangesLeave')}</DialogDescription>
                </DialogHeader>
                <DialogFooter>
                    {
                        assistantState.status !== OnlineState.OnLine && <Button className="leave" onClick={handleUiRequest(handleSaveAndClose)}>
                            {t('build.leaveAndSave')}
                        </Button>
                    }
                    <Button variant="solid" onClick={() => blocker.proceed?.()} color="danger">
                        {t('build.leaveWithoutSave')}
                    </Button>
                    <Button variant="outlined" onClick={() => {
                        blocker.reset?.()
                    }} color="default">
                        {t('cancel')}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    </div>
};


// Save prompt when leaving page
const useBeforeUnload = (changed, checking) => {
    const { t } = useTranslation()

    // Prompt to save when leaving. Only with unsaved changes: the browser dialog
    // otherwise shows on every reload or back step that leaves the page.
    useEffect(() => {
        if (checking || !changed) return
        const fun = (e) => {
            const confirmationMessage = `${t('flow.unsavedChangesConfirmation')}`;
            (e || window.event).returnValue = confirmationMessage; // Compatible with different browsers
            return confirmationMessage;
        }
        window.addEventListener('beforeunload', fun);
        return () => { window.removeEventListener('beforeunload', fun) }
    }, [checking, changed])

    return useBlocker(changed);
}

export default function EditAssistant() {
    return <AssistantMessageStoreProvider><EditAssistantContent /></AssistantMessageStoreProvider>;
}
