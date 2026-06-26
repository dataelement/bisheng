import { useEffect, useMemo, useState, useRef } from "react";
import { useRecoilState, useRecoilValue } from "recoil";
import { Button, SendIcon, Textarea } from "~/components";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { useRecordingAudioLoading } from "~/components/Voice/textToSpeechStore";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import { useLocalize } from "~/hooks";
import { Database, Paperclip } from "lucide-react";
import InputFiles from "./components/InputFiles";
import { bishengConfState, currentRunningState, runtimeKnowledgeSelectionState } from "./store/atoms";
import { useAreaText } from "./useAreaText";
import DragDropOverlay from "~/components/Chat/Input/Files/DragDropOverlay";
import { useFileDropAndPaste } from "./useFileDropAndPaste";
import UserSelectedKnowledgePicker from "./UserSelectedKnowledgePicker";
import {
    hasUserSelectedKnowledgeNode,
    isRuntimeKnowledgePickerDisabled,
    RuntimeKnowledgeSelection,
    shouldRenderRuntimeKnowledgePicker,
	validateRuntimeKnowledgeSelection,
} from "./userSelectedKnowledge";

const getRuntimeKnowledgeLabel = (selection?: RuntimeKnowledgeSelection | null) => {
    if (!selection) return "选择知识空间";
    if (selection.mode === "source" && selection.whole_source?.source_name) {
        return selection.whole_source.source_name;
    }
    const count = selection.effective_file_count ?? selection.items?.length ?? 0;
    return count > 0 ? `已选 ${count} 个范围` : "选择知识空间";
};

const isPortalWorkflowEmbedRequest = () => {
    if (typeof window === "undefined") return false;
    const params = new URLSearchParams(window.location.search);
    return params.get("portal_embed") === "1" || window.location.pathname.includes("/portal-chat/workflow/auth/");
};

export default function ChatInput({ readOnly, v, portalWorkflowMode = false }) {
    const effectivePortalWorkflowMode = portalWorkflowMode || isPortalWorkflowEmbedRequest();
    const [bishengConfig] = useRecoilState(bishengConfState);
    const { inputDisabled, error: inputMsg, showUpload, showStop, showReRun, inputForm } = useRecoilValue(currentRunningState);
    // useAreaText
    const {
        accepts,
        inputRef,
        setChatFiles,
        handleInput,
        handleRestart,
        handleSendClick,
        handleRuntimeKnowledgeSubmit,
        handleStopClick,
        chatState,
    } = useAreaText({ deferRuntimeKnowledgeSelection: effectivePortalWorkflowMode });

    const [fileUploading, setFileUploading] = useState(false);
    const [runtimeKnowledgePanelOpen, setRuntimeKnowledgePanelOpen] = useState(false);
    const [audioOpening] = useRecordingAudioLoading();
    const localize = useLocalize();
    const { data: modelData } = useGetWorkbenchModelsQuery();
    const showVoice = modelData?.asr_model.id;
    const [runtimeKnowledgeSelection, setRuntimeKnowledgeSelection] = useRecoilState<RuntimeKnowledgeSelection | null>(runtimeKnowledgeSelectionState);
    const runtimeKnowledgeInputForm = inputForm?.tab === "runtime_knowledge" ? inputForm : null;
    const requiresRuntimeKnowledge = useMemo(
        () => hasUserSelectedKnowledgeNode(chatState?.flow),
        [chatState?.flow],
    );
    const hasActiveInputForm = Boolean(inputForm);
    const canShowRuntimeKnowledgePicker = shouldRenderRuntimeKnowledgePicker({
        requiresRuntimeKnowledge,
        inputDisabled,
        hasInputForm: hasActiveInputForm,
        readOnly,
	    });
    const showRuntimeKnowledgePicker = requiresRuntimeKnowledge && (
        (canShowRuntimeKnowledgePicker && runtimeKnowledgePanelOpen) || Boolean(runtimeKnowledgeInputForm)
    );
    const runtimeKnowledgeSelectionError = requiresRuntimeKnowledge
        ? validateRuntimeKnowledgeSelection(runtimeKnowledgeSelection)
        : "";
    const runtimeKnowledgeLabel = getRuntimeKnowledgeLabel(runtimeKnowledgeSelection);
    const runtimeKnowledgePickerDisabled = isRuntimeKnowledgePickerDisabled({
        inputDisabled,
        hasInputForm: hasActiveInputForm,
        readOnly,
    });

    const inputFilesRef = useRef(null);

    // handle drop and paste
    const { isDragging, handlePaste } = useFileDropAndPaste({
        enabled: showUpload && !readOnly && !inputDisabled,
        onFilesReceived: (files) => {
            inputFilesRef.current?.upload(files);
        }
    });

    // ... Placeholder 和 AutoFocus 逻辑保持不变 ...
    const placholder = useMemo(() => {
        return inputDisabled ?
            (inputMsg.code ? localize(`api_errors.${inputMsg.code}`, inputMsg.data) : ' ')
            : localize('com_ui_please_enter_question')
    }, [inputDisabled, inputMsg, localize]);

    useEffect(() => {
        inputDisabled && setTimeout(() => {
            inputRef.current?.focus()
        }, 60)
    }, [inputDisabled]);

    useEffect(() => {
        setRuntimeKnowledgeSelection(null);
    }, [chatState?.flow?.id]);

    useEffect(() => {
        if (runtimeKnowledgeInputForm) {
            setRuntimeKnowledgePanelOpen(true);
        }
    }, [runtimeKnowledgeInputForm?.node_id]);

    const handleRuntimeSend = () => {
        handleSendClick("", runtimeKnowledgeSelection);
    };

    const handleConfirmRuntimeKnowledge = () => {
        if (runtimeKnowledgeSelectionError) return;
        if (!runtimeKnowledgeInputForm) {
            setRuntimeKnowledgePanelOpen(false);
            return;
        }
        const submitted = handleRuntimeKnowledgeSubmit(runtimeKnowledgeInputForm.node_id, runtimeKnowledgeSelection);
        if (submitted) {
            setRuntimeKnowledgePanelOpen(false);
        }
    };

    const renderRuntimeKnowledgePickerPanel = (variant: "portal" | "default" = "default") => (
        <div className={`absolute right-4 z-30 w-[min(560px,calc(100%-2rem))] ${variant === "portal" ? "bottom-[116px]" : "bottom-[108px]"}`}>
            <UserSelectedKnowledgePicker
                disabled={runtimeKnowledgePickerDisabled}
                value={runtimeKnowledgeSelection}
                onChange={setRuntimeKnowledgeSelection}
                showConfirm={variant === "portal" || Boolean(runtimeKnowledgeInputForm)}
                confirmDisabled={Boolean(runtimeKnowledgeSelectionError)}
                confirmLabel="确认"
                onConfirm={handleConfirmRuntimeKnowledge}
                onCancel={() => setRuntimeKnowledgePanelOpen(false)}
            />
        </div>
    );

    if (effectivePortalWorkflowMode) {
        return (
            <div className="z-10 w-full shrink-0 bg-[#fff] dark:bg-[#1B1B1B]">
                <div className="relative mx-auto w-full max-w-[690px] px-4 pb-3">
                    {isDragging && <DragDropOverlay />}

                    {showRuntimeKnowledgePicker && renderRuntimeKnowledgePickerPanel("portal")}

                    <div className="rounded-lg border border-[#c8d8f0] bg-white shadow-[0_2px_8px_rgba(26,63,168,0.06)] transition-all focus-within:border-[#2d6ef5] focus-within:shadow-[0_0_0_3px_rgba(45,110,245,0.10),0_2px_8px_rgba(26,63,168,0.06)]">
                        {showUpload && (
                            <InputFiles
                                ref={inputFilesRef}
                                v={v}
                                showVoice={showVoice}
                                accepts={accepts}
                                disabled={readOnly || audioOpening || inputDisabled}
                                size={bishengConfig?.uploaded_files_maximum_size || 50}
                                hideTrigger
                                onChange={(files => {
                                    setFileUploading(!files);
                                    setChatFiles(files);
                                })}
                            />
                        )}
                        <div className="flex items-start gap-2 px-4 pb-2 pt-3">
                            <Textarea
                                id="bs-send-input"
                                ref={inputRef}
                                rows={2}
                                style={{ height: 42 }}
                                disabled={readOnly || inputDisabled}
                                onInput={handleInput}
                                onPaste={handlePaste}
                                onKeyDown={(event) => {
                                    if (event.key === "Enter" && !event.shiftKey) {
                                        event.preventDefault();
                                        !inputDisabled && handleRuntimeSend()
                                    }
                                }}
                                placeholder={inputDisabled ? " " : "开始提问..."}
                                className="min-h-[42px] flex-1 resize-none border-none bg-transparent p-0 pr-2 text-[14px] leading-[1.5] text-[#1a2a4a] outline-none scrollbar-hide placeholder:text-[#b0bcd0]"
                            />
                            <div className="flex shrink-0 items-center gap-1.5">
                                {showVoice && (
                                    <SpeechToTextComponent
                                        disabled={inputDisabled || readOnly || showStop}
                                        onChange={(e) => inputRef.current.value += e}
                                    />
                                )}
                                {showUpload && (
                                    <button
                                        type="button"
                                        className="inline-flex h-8 w-8 items-center justify-center rounded-[5px] text-[#8a9ab8] transition-colors hover:bg-[#eef2fc] hover:text-[#2d6ef5] disabled:cursor-not-allowed disabled:opacity-50"
                                        disabled={readOnly || audioOpening || inputDisabled}
                                        onClick={() => inputFilesRef.current?.openPicker?.()}
                                        aria-label="上传附件"
                                    >
                                        <Paperclip size={16} />
                                    </button>
                                )}
                                {showStop ? (
                                    <button
                                        type="button"
                                        className="inline-flex h-8 w-8 items-center justify-center rounded-[5px] bg-[#2d6ef5]"
                                        onClick={handleStopClick}
                                        aria-label="停止生成"
                                    >
                                        <span className="size-3 rounded-[2px] bg-white" />
                                    </button>
                                ) : (
                                    <button
                                        id="bs-send-btn"
                                        type="button"
                                        className="inline-flex h-8 w-8 items-center justify-center rounded-[5px] bg-gradient-to-br from-[#1a3fa8] to-[#2d6ef5] text-white transition-opacity hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-50 [&>svg]:text-white"
                                        disabled={inputDisabled || fileUploading || readOnly || audioOpening}
                                        onClick={() => { !inputDisabled && !fileUploading && handleRuntimeSend() }}
                                        aria-label="发送"
                                    >
                                        <SendIcon size={20} />
                                    </button>
                                )}
                            </div>
                        </div>
                        <div className="flex min-h-[34px] items-center gap-2 px-4 pb-2">
                            <span className="min-w-0 flex-1 text-[11px] text-[#b0bcd0]">{showUpload ? "支持上传单文档和图片" : ""}</span>
                            {requiresRuntimeKnowledge && (
                                <button
                                    type="button"
                                    className="inline-flex min-h-[26px] items-center gap-1 rounded px-2 text-xs text-[#6a80a8] transition-colors hover:bg-[#eef2fc] hover:text-[#2d6ef5] disabled:cursor-not-allowed disabled:text-[#b8c4d8]"
                                    disabled={runtimeKnowledgePickerDisabled && !runtimeKnowledgeInputForm}
                                    onClick={() => setRuntimeKnowledgePanelOpen(true)}
                                >
                                    <Database size={14} />
                                    <span className="max-w-[180px] truncate">{runtimeKnowledgeLabel}</span>
                                </button>
                            )}
                        </div>
                    </div>
                    <p className="pb-1 pt-2 text-center text-sm text-gray-400">{bishengConfig?.dialog_tips}</p>
                    <div className="absolute left-0 -top-14 flex w-full justify-center">
                        {showReRun && !inputMsg.code && !showStop && <Button
                            className="rounded-full bg-primary/10 bg-blue-50 text-primary"
                            variant="ghost"
                            disabled={readOnly}
                            onClick={handleRestart}>
                            <img className='size-5' src={__APP_ENV__.BASE_URL + '/assets/chat.png'} alt="" />{localize('com_ui_restart')}
                        </Button>
                        }
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="z-10 w-full shrink-0 bg-[#fff] dark:bg-[#1B1B1B]">
            <div className="relative mx-auto w-full max-w-[800px] px-4 pt-1">
                {/* drag upload overlay */}
                {isDragging && <DragDropOverlay />}

                {showRuntimeKnowledgePicker && renderRuntimeKnowledgePickerPanel("default")}

                <div className="relative px-4 rounded-3xl bg-surface-tertiary">
                {/* attr file */}
                {showUpload && <InputFiles
                    ref={inputFilesRef}
                    v={v}
                    showVoice={showVoice}
                    accepts={accepts}
                    disabled={readOnly || audioOpening || inputDisabled}
                    size={bishengConfig?.uploaded_files_maximum_size || 50}
                    onChange={(files => {
                        setFileUploading(!files);
                        setChatFiles(files);
                    })} />}

                {/* send input */}
                <div className="flex gap-2 absolute right-3 bottom-3 z-10">
                    {showVoice && <SpeechToTextComponent disabled={inputDisabled || readOnly || showStop} onChange={(e) => inputRef.current.value += e} />}
                    {showStop ?
                        <div
                            className="w-8 h-8 bg-primary rounded-full cursor-pointer flex justify-center items-center"
                            onClick={handleStopClick}
                        >
                            <div className="size-3 bg-white rounded-[2px]"></div>
                        </div> :
                        <button
                            id="bs-send-btn"
                            className="size-8 flex items-center justify-center rounded-full bg-primary text-white transition-all duration-200 disabled:cursor-not-allowed disabled:bg-[#E5E6EB] disabled:text-[#86909C] disabled:opacity-100 [&>svg]:text-white disabled:[&>svg]:text-[#4E5969]"
                            disabled={inputDisabled || fileUploading || readOnly || audioOpening}
                            onClick={() => { !inputDisabled && !fileUploading && handleRuntimeSend() }}>
                            <SendIcon size={24} />
                        </button>
                    }
                </div>

                {/*
                    stop & 重置
                    is工作流 & 未展示停止按钮 & 没有错误消息
                */}
                <div className="absolute w-full flex justify-center left-0 -top-14">
                    {/* {!showStop && chatState?.flow?.flow_type === 10 && !inputMsg  & 运行结束展示 */}
                    {showReRun && !inputMsg.code && !showStop && <Button
                        className="rounded-full bg-primary/10 bg-blue-50 text-primary"
                        variant="ghost"
                        disabled={readOnly}
                        onClick={handleRestart}>
                        <img className='size-5' src={__APP_ENV__.BASE_URL + '/assets/chat.png'} alt="" />{localize('com_ui_restart')}
                    </Button>
                    }
                </div>

                {/* input */}
                <Textarea
                    id="bs-send-input"
                    ref={inputRef}
                    rows={2}
                    style={{ height: 56 }}
                    disabled={readOnly || inputDisabled}
                    onInput={handleInput}
                    onPaste={handlePaste}
                    onKeyDown={(event) => {
                        if (event.key === "Enter" && !event.shiftKey) {
                            event.preventDefault();
                            !inputDisabled && handleRuntimeSend()
                        }
                    }}
                    placeholder={placholder}
                    className={"resize-none bg-transparent border-none p-4 pr-10 text-md min-h-24 max-h-80 scrollbar-hide"}
                ></Textarea>
                </div>
                <p className="text-center text-sm pt-2 pb-4 text-gray-400">{bishengConfig?.dialog_tips}</p>
            </div>
        </div>
    );
};
