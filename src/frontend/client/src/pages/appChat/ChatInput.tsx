// @ts-strict-ignore
import { useEffect, useMemo, useState, useRef } from "react";
import { useRecoilState, useRecoilValue } from "recoil";
import { ConversationComposer } from '@bisheng/chat';
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { useRecordingAudioLoading } from "~/components/Voice/textToSpeechStore";
import { useVoiceModels } from "~/hooks/useVoice";
import { useLocalize } from "~/hooks";
import InputFiles from "./components/InputFiles";
import { bishengConfState, currentRunningState } from "./store/atoms";
import { useAreaText } from "./useAreaText";
import DragDropOverlay from "~/components/Chat/Input/Files/DragDropOverlay";
import { useFileDropAndPaste } from "./useFileDropAndPaste";

export default function ChatInput({ readOnly, v }) {
    const [bishengConfig] = useRecoilState(bishengConfState);
    const { inputDisabled, error: inputMsg, showUpload, showStop, showReRun } = useRecoilValue(currentRunningState);
    // useAreaText
    const { accepts, inputRef, setChatFiles, handleRestart, handleSendClick, handleStopClick } = useAreaText();

    const [fileUploading, setFileUploading] = useState(false);
    const [fileCount, setFileCount] = useState(0);
    const [audioOpening] = useRecordingAudioLoading();
    const localize = useLocalize();
    const { data: modelData } = useVoiceModels();
    const showVoice = modelData?.asr_model?.id;

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
            (inputMsg.code ? localize(`api_errors.${inputMsg.code}`, { ...(inputMsg.data || {}), defaultValue: localize('api_errors.fallback') }) : ' ')
            : localize('com_ui_please_enter_question')
    }, [inputDisabled, inputMsg, localize]);

    useEffect(() => {
        inputDisabled && setTimeout(() => {
            inputRef.current?.focus()
        }, 60)
    }, [inputDisabled]);

    return <ConversationComposer inputRef={inputRef} canExecute={!readOnly} inputDisabled={inputDisabled}
        busy={fileUploading || audioOpening} hasAttachments={fileCount > 0} showStop={showStop}
        showRestart={showReRun && !inputMsg.code && !showStop}
        labels={{ attach: localize('shared:app_chat.attach'), send: localize('shared:app_chat.send'), stop: localize('com_ui_stop'), restart: localize('com_ui_restart') }}
        placeholder={placholder} hint={bishengConfig?.dialog_tips}
        onSend={() => { handleSendClick(); setFileCount(0); }} onStop={handleStopClick} onRestart={handleRestart}
        onAttach={showUpload ? () => inputFilesRef.current?.openPicker() : undefined} attachmentDisabled={audioOpening}
        onPaste={handlePaste} overlay={isDragging ? <DragDropOverlay /> : undefined}
        voice={showVoice ? <SpeechToTextComponent disabled={inputDisabled || readOnly || showStop} onChange={text => {
            if (inputRef.current) { inputRef.current.value += text; inputRef.current.dispatchEvent(new Event('input', { bubbles: true })); }
        }} /> : undefined}
        attachments={showUpload ? <InputFiles hideTrigger ref={inputFilesRef} v={v} showVoice={showVoice} accepts={accepts}
            disabled={readOnly || audioOpening || inputDisabled} size={bishengConfig?.uploaded_files_maximum_size || 50}
            onChange={files => {
                if (files === null) { setFileUploading(true); return; }
                setFileUploading(false); setFileCount(files.length); setChatFiles(files);
            }} /> : undefined} />;
}
