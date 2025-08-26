import { RefreshCw, SendIcon } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useRecoilState, useRecoilValue } from "recoil";
import { Button, Textarea } from "~/components";
import InputFiles from "./components/InputFiles";
import { bishengConfState, currentRunningState } from "./store/atoms";
import { useAreaText } from "./useAreaText";

export default function ChatInput({ v }) {
    const [bishengConfig] = useRecoilState(bishengConfState)
    const { inputDisabled, error: inputMsg, showUpload, showStop } = useRecoilValue(currentRunningState)
    const { accepts, chatState, inputRef, setChatFiles, handleInput, handleRestart, handleSendClick, handleStopClick } = useAreaText()

    const placholder = useMemo(() => {
        const reason = inputMsg || ' '
        return inputDisabled ? reason : '请输入问题'
    }, [inputDisabled])

    // auto focus
    useEffect(() => {
        inputDisabled && setTimeout(() => {
            inputRef.current?.focus()
        }, 60)
    }, [inputDisabled])


    const fileUploading = false


    return <div className="absolute bottom-0 w-full pt-1 bg-[#fff] dark:bg-[#1B1B1B]">
        <div className="relative px-4">
            {/* 引导问题 */}

            {/* 附件 */}
            {showUpload && !inputDisabled && <InputFiles accepts={accepts} size={bishengConfig?.uploaded_files_maximum_size || 50} v={v} onChange={setChatFiles} />}
            {/* send */}
            <div className="flex gap-2 absolute right-7 top-4 z-10">
                {showStop ?
                    <div
                        className="w-6 h-6 rounded-sm hover:bg-gray-200 dark:hover:bg-gray-950 cursor-pointer flex justify-center items-center"
                        onClick={handleStopClick}
                    >
                        <div className="size-4 bg-gray-900 rounded-sm"></div>
                    </div> :
                    <div
                        id="bs-send-btn"
                        className="w-6 h-6 rounded-sm hover:bg-gray-200 dark:hover:bg-gray-950 cursor-pointer flex justify-center items-center"
                        onClick={() => { !inputDisabled && !fileUploading && handleSendClick() }}>
                        <SendIcon size={20} className={`${inputDisabled || fileUploading ? 'text-muted-foreground' : 'text-foreground'}`} />
                    </div>
                }
            </div>
            {/* stop & 重置 */}
            <div className="absolute w-full flex justify-center left-0 -top-14">
                {!showStop && chatState?.flow?.flow_type === 10 && <Button
                    className="rounded-full bg-[#fff] dark:bg-[#1B1B1B]"
                    variant="outline"
                    onClick={handleRestart}>
                    <RefreshCw className="mr-1" size={16} />重新运行
                </Button>
                }
            </div>
            <Textarea
                id="bs-send-input"
                ref={inputRef}
                rows={1}
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
                className={"resize-none py-4 pr-10 text-md min-h-6 max-h-[200px] scrollbar-hide dark:bg-[#131415]"}
            ></Textarea>
        </div>
        <p className="text-center text-sm pt-2 pb-4 text-gray-400">{bishengConfig?.dialog_tips}</p>
    </div>
};
