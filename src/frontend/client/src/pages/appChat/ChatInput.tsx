import { useEffect, useMemo, useState } from "react";
import { useRecoilState, useRecoilValue } from "recoil";
import { Button, SendIcon, Textarea } from "~/components";
import InputFiles from "./components/InputFiles";
import { bishengConfState, currentRunningState } from "./store/atoms";
import { useAreaText } from "./useAreaText";

export default function ChatInput({ v }) {
    const [bishengConfig] = useRecoilState(bishengConfState)
    const { inputDisabled, error: inputMsg, showUpload, showStop, showReRun } = useRecoilValue(currentRunningState)
    const { accepts, chatState, inputRef, setChatFiles, handleInput, handleRestart, handleSendClick, handleStopClick } = useAreaText()
    const [fileUploading, setFileUploading] = useState(false)

    const placholder = useMemo(() => {
        const reason = inputMsg || ' '
        return inputDisabled ? reason : '请输入问题'
    }, [inputDisabled, inputMsg])

    // auto focus
    useEffect(() => {
        inputDisabled && setTimeout(() => {
            inputRef.current?.focus()
        }, 60)
    }, [inputDisabled])

    return <div className="absolute bottom-0 w-full pt-1 bg-[#fff] dark:bg-[#1B1B1B]">
        <div className="relative px-4 rounded-3xl bg-surface-tertiary ">
            {/* 附件 */}
            {showUpload && !inputDisabled && <InputFiles
                v={v}
                accepts={accepts}
                size={bishengConfig?.uploaded_files_maximum_size || 50}
                onChange={(files => {
                    setFileUploading(!files)
                    setChatFiles(files)
                })} />}
            {/* send */}
            <div className="flex gap-2 absolute right-3 bottom-3 z-10">
                {showStop ?
                    <div
                        className="w-8 h-8 bg-primary rounded-full cursor-pointer flex justify-center items-center"
                        onClick={handleStopClick}
                    >
                        <div className="size-3 bg-white rounded-[2px]"></div>
                    </div> :
                    <button
                        id="bs-send-btn"
                        className="size-8 flex items-center justify-center rounded-full bg-primary text-white transition-all duration-200 disabled:cursor-not-allowed disabled:text-text-secondary disabled:opacity-20"
                        disabled={inputDisabled || fileUploading}
                        onClick={() => { !inputDisabled && !fileUploading && handleSendClick() }}>
                        <SendIcon size={24} />
                    </button>
                }
            </div>
            {/* 
                stop & 重置 
                is工作流 & 未展示停止按钮 & 没有错误消息
            */}
            <div className="absolute w-full flex justify-center left-0 -top-14">
                {/* {!showStop && chatState?.flow?.flow_type === 10 && !inputMsg  */}
                { showReRun && !inputMsg && <Button
                    className="rounded-full bg-primary/10 bg-blue-50 text-primary"
                    variant="ghost"
                    onClick={handleRestart}>
                    <img className='size-5' src={__APP_ENV__.BASE_URL + '/assets/chat.png'} alt="" />重新运行
                </Button>
                }
            </div>
            <Textarea
                id="bs-send-input"
                ref={inputRef}
                rows={2}
                style={{ height: 56 }}
                disabled={inputDisabled}
                onInput={handleInput}
                onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                        event.preventDefault();
                        !inputDisabled && handleSendClick()
                    }
                }}
                placeholder={placholder}
                className={"resize-none bg-transparent border-none p-4 pr-10 text-md min-h-24 max-h-80 scrollbar-hide"}
            ></Textarea>
        </div>
        <p className="text-center text-sm pt-2 pb-4 text-gray-400">{bishengConfig?.dialog_tips}</p>
    </div>
};
