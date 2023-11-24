import { FileUp, Send, StopCircle } from "lucide-react";
import { forwardRef, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import ShadTooltip from "../../../components/ShadTooltipComponent";
import { Button } from "../../../components/ui/button";
import { ChatMessageType } from "../../../types/chat";
import { ChatMessage } from "./ChatMessage";
import ResouceModal from "./ResouceModal";

interface Iprops {
    sendUserName: string
    chatId: string
    inputState: any
    fileInputs: any[]
    isReport: boolean
    isRoom: boolean
    flowName: string
    stopState: boolean
    messages: ChatMessageType[]
    changeHistoryByScroll: boolean
    onStopClick: () => void
    onNextPageClick: () => void
    onUploadFile: () => void
    onSendMsg: (msg: string) => void
}

export default forwardRef(function ChatPanne({
    chatId, messages, inputState, fileInputs, changeHistoryByScroll, flowName, stopState, isRoom, isReport, sendUserName,
    onSendMsg, onUploadFile, onNextPageClick, onStopClick
}: Iprops, inputRef: any) {

    const { t } = useTranslation()

    const inputDisable = inputState.lock || (fileInputs?.length && messages.length === 0)
    const handleSend = () => {
        const val = inputRef.current?.value
        setTimeout(() => {
            if (inputRef.current) {
                inputRef.current.value = ''
                inputRef.current.style.height = 'auto'
            }
            setInputEmpty(true)
        }, 100);

        if (val.trim() === '' || inputDisable) return
        onSendMsg(val)
    }

    // 消息滚动
    const messagesRef = useRef(null);
    useEffect(() => {
        if (messagesRef.current && !changeHistoryByScroll) { // 滚动加载不触发
            messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
        }
    }, [messages, changeHistoryByScroll]);

    // 消息滚动加载
    useEffect(() => {
        function handleScroll() {
            if (messagesRef.current.scrollTop <= 30) {
                onNextPageClick()
            }
        }

        messagesRef.current?.addEventListener('scroll', handleScroll);
        return () => messagesRef.current?.removeEventListener('scroll', handleScroll)
    }, [messagesRef.current]);

    // input 滚动
    const [inputEmpty, setInputEmpty] = useState(true)
    useEffect(() => {
        setInputEmpty(true)
        if (inputRef.current) inputRef.current.value = ''
    }, [chatId])
    const handleTextAreaHeight = (e) => {
        const textarea = e.target
        textarea.style.height = 'auto'
        textarea.style.height = textarea.scrollHeight + 'px'
        setInputEmpty(textarea.value.trim() === '')
    }

    // 溯源
    const [souce, setSouce] = useState<ChatMessageType>(null)


    return <div className="h-screen overflow-hidden relative">
        <div className="absolute px-2 py-2 bg-[#fff] z-10 dark:bg-gray-950 text-sm text-gray-400 font-bold">{flowName}</div>
        <div className="chata mt-14" style={{ height: 'calc(100vh - 5rem)' }}>
            <div ref={messagesRef} className={`chat-panne h-full overflow-y-scroll no-scrollbar px-4 ${isRoom || isReport ? 'pb-40' : 'pb-20'}`}>
                {
                    messages.map((c, i) => <ChatMessage key={c.id || i} userName={sendUserName} chat={c} onSource={() => setSouce(c)}></ChatMessage>)
                }
            </div>
            <div className="absolute w-full bottom-0 bg-gradient-to-t from-[#fff] to-[rgba(255,255,255,0.8)] px-8 dark:bg-gradient-to-t dark:from-[#000] dark:to-[rgba(0,0,0,0.8)]">
                <div className={`w-full text-area-box border border-gray-600 rounded-lg my-6 overflow-hidden pr-2 py-2 relative ${(inputState.lock || (fileInputs?.length && messages.length === 0)) && 'bg-gray-200 dark:bg-gray-600'}`}>
                    <textarea id='input'
                        ref={inputRef}
                        disabled={isReport || inputDisable} style={{ height: 36 }} rows={1}
                        className={`w-full resize-none border-none bg-transparent outline-none px-4 pt-1 text-xl max-h-[200px]`}
                        placeholder={t('chat.inputPlaceholder')}
                        onInput={handleTextAreaHeight}
                        onKeyDown={(event) => {
                            if (event.key === "Enter" && !event.shiftKey) handleSend()
                        }}></textarea>
                    <div className="absolute right-6 bottom-4 flex gap-2">
                        {!isReport && <ShadTooltip content={t('chat.uploadFileTooltip')}>
                            <button disabled={inputState.lock || !fileInputs?.length} className="disabled:text-gray-400" onClick={onUploadFile}><FileUp /></button>
                        </ShadTooltip>}
                        <ShadTooltip content={t('chat.sendTooltip')}>
                            <button disabled={isReport || inputEmpty || inputDisable} className=" disabled:text-gray-400" onClick={handleSend}><Send /></button>
                        </ShadTooltip>
                    </div>
                    {inputState.errorCode && <div className="bg-gray-200 absolute top-0 left-0 w-full h-full text-center text-gray-400 align-middle pt-4">{t(`status.${inputState.errorCode}`)}</div>}
                </div>
            </div>
        </div>
        {(isRoom || isReport) && <div className=" absolute w-full flex justify-center bottom-32">
            <Button className="rounded-full" variant="outline" disabled={stopState} onClick={onStopClick}><StopCircle className="mr-2" />Stop</Button>
        </div>}
        {/* 源文件类型 */}
        <ResouceModal chatId={chatId} open={!!souce} data={souce} setOpen={() => setSouce(null)}></ResouceModal>
    </div>
});
