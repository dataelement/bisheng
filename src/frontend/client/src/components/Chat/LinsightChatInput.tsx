/**
 * Simplified chat input with configurable toolbar.
 * Features: file upload (InputFiles + drag/paste), voice input (STT),
 * model/knowledge/tools selectors, mutual exclusion for kb/tools/files.
 */
import {
    memo,
    useCallback,
    useEffect,
    useRef,
    useState,
    type KeyboardEvent
} from "react";
import { useNavigate } from "react-router-dom";
import { useRecoilState } from "recoil";
import { File_Accept } from "~/common";
import { LinsiTools } from "~/components/Chat/Input/ChatFormTools";
import DragDropOverlay from "~/components/Chat/Input/Files/DragDropOverlay";
import { SendIcon } from "~/components/svg";
import { Button, TextareaAutosize } from "~/components/ui";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { useGetUserLinsightCountQuery, useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import { useLocalize } from "~/hooks";
import { useLinsightSessionManager } from "~/hooks/useLinsightManager";
import InputFiles from "~/pages/appChat/components/InputFiles";
import { useFileDropAndPaste } from "~/pages/appChat/useFileDropAndPaste";
import { cn, removeFocusRings } from "~/utils";
import SameSopSpan, { sameSopLabelState } from "./Input/SameSopSpan";

export interface LinsightChatInputFeatures {
    modelSelect?: boolean;
    knowledgeBase?: boolean;
    tools?: boolean;
    fileUpload?: boolean;
    voiceInput?: boolean;
}

interface LinsightChatInputProps {
    size?: '' | 'mini';
    disabled?: boolean;
    isStreaming?: boolean;
    onSend: (text: string, files?: any[] | null) => void;
    onStop: () => void;
    onNewChat: () => void;
    value?: string;
    onChange?: (val: string) => void;
    /** Config for knowledge base and tools */
    bsConfig?: any;
    /** Support Lingsi mode UI differences */
    isLingsi?: boolean;
    setShowCode?: (show: boolean) => void;
}

const LinsightChatInput = memo(
    ({
        size = '',
        disabled = false,
        isStreaming = false,
        onSend,
        onStop,
        value: externalValue,
        onChange: onExternalChange,
        bsConfig,
        isLingsi = false,
        setShowCode,
    }: LinsightChatInputProps) => {
        const isControlled = externalValue !== undefined;
        const [internalText, setInternalText] = useState("");
        const text = isControlled ? externalValue : internalText;
        const setText = useCallback(
            (val: string) => {
                if (isControlled) {
                    onExternalChange?.(val);
                } else {
                    setInternalText(val);
                }
            },
            [isControlled, onExternalChange]
        );
        const textAreaRef = useRef<HTMLTextAreaElement>(null);
        const navigator = useNavigate();

        // File upload state
        const [fileUploading, setFileUploading] = useState(false);
        const [chatFiles, setChatFiles] = useState<any[] | null>(null);
        const inputFilesRef = useRef<any>(null);
        // linsight tools
        const [linsightTools, setLinsightTools] = useState([]);

        // Voice input: check if ASR model is available
        const { data: modelData } = useGetWorkbenchModelsQuery();
        const showVoice = !!modelData?.asr_model?.id;

        const localize = useLocalize();
        const { data: count, refetch } = useGetUserLinsightCountQuery();

        useEffect(() => {
            bsConfig?.linsight_invitation_code && refetch();
        }, [bsConfig?.linsight_invitation_code]);


        // Drag & paste file support (only when not disabled by exclusion)
        const { isDragging, handlePaste } = useFileDropAndPaste({
            enabled: !disabled,
            onFilesReceived: (files: FileList | File[]) => {
                inputFilesRef.current?.upload(files);
            },
        });

        // Auto-focus when controlled value is set externally (e.g. preset question)
        useEffect(() => {
            if (isControlled && externalValue) {
                textAreaRef.current?.focus();
            }
        }, [externalValue, isControlled]);

        console.log('chatFiles :>> ', chatFiles);
        const { setLinsightSubmission } = useLinsightSessionManager('new')
        const [sameSopLabel, setSameSopLabel] = useRecoilState(sameSopLabelState)

        const biu = (trimmed) => {
            if (bsConfig?.linsight_invitation_code && count === 0)
                return setShowCode?.(true);
            setLinsightSubmission('new', {
                sameSopId: sameSopLabel?.id || undefined,
                isNew: true,
                files: Array.from(chatFiles || []).map(item => ({
                    file_id: item.file_id,
                    file_name: item.filename || item.name,
                    parsing_status: 'completed'
                })),
                question: trimmed,
                // feedback: '',
                tools: linsightTools,
                model: 'gpt-4',
                enableWebSearch: false,
                useKnowledgeBase: true,
            });

            // submitMessage({
            //     text: trimmed,
            //     files: chatFiles,
            //     tools: linsightTools,
            //     linsight: true,
            //     knowledge: {},
            // });
            setChatFiles([])
            setSameSopLabel(null)
            navigator("/linsight/new");
        }

        const handleSend = useCallback(() => {
            const trimmed = text.trim();
            if ((!trimmed && !chatFiles?.length) || disabled || isStreaming || fileUploading) return;
            // Pass files through to parent
            // onSend(trimmed, chatFiles);
            biu(trimmed)
            setText("");
            setChatFiles(null);
            inputFilesRef.current?.clear();
            // Reset textarea height
            if (textAreaRef.current) {
                textAreaRef.current.style.height = "auto";
            }
        }, [text, disabled, isStreaming, fileUploading, onSend, chatFiles, sameSopLabel, linsightTools, bsConfig, count]);

        const handleKeyDown = useCallback(
            (e: KeyboardEvent<HTMLTextAreaElement>) => {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    if (isStreaming) return;
                    handleSend();
                }
            },
            [handleSend, isStreaming]
        );

        return (
            <div className={cn("px-4 pb-4 shrink-0 relative", !isLingsi && "overflow-hidden")}>
                {/* Drag-drop overlay */}
                {isDragging && <DragDropOverlay />}

                <div className={`relative pb-3 z-10 flex w-full flex-col bg-surface-tertiary overflow-hidden border border-blue-400 bg-gradient-to-b from-[#F2F5FF] to-white ${size === 'mini' ? 'rounded-xl' : 'rounded-3xl'}`}>
                    {/* 做同款 label */}
                    {isLingsi && <SameSopSpan />}
                    {/* File upload area: file list + attachment button */}
                    {(() => {
                        const InputFilesAny = InputFiles as any;
                        const accept = isLingsi ? (bsConfig?.enable_etl4lm ? File_Accept.Linsight_Etl4lm : File_Accept.Linsight) : "";
                        return <InputFilesAny
                            ref={inputFilesRef}
                            v={""}
                            showVoice={showVoice}
                            accepts={accept}
                            uploadMode="linsight"
                            size={bsConfig?.uploaded_files_maximum_size || 50}
                            onChange={(files: any) => {
                                setFileUploading(!files);
                                setChatFiles(files);
                            }}
                        />;
                    })()}

                    {/* Textarea */}
                    <TextareaAutosize
                        ref={textAreaRef}
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        onKeyDown={handleKeyDown}
                        onPaste={handlePaste}
                        disabled={disabled}
                        placeholder={bsConfig?.linsightConfig?.input_placeholder}
                        tabIndex={0}
                        data-testid="ai-chat-input"
                        rows={2}
                        style={{ height: 84, overflowY: "auto" }}
                        className={cn(
                            "p-3 pb-0 m-0 w-full resize-none bg-transparent text-sm",
                            "placeholder-black/50 dark:placeholder-white/50",
                            "max-h-96 pl-4 pr-6",
                            size === 'mini' ? 'min-h-0' : 'min-h-20',
                            removeFocusRings,
                            "transition-[max-height] duration-200"
                        )}
                    />

                    <div className="relative h-8">
                        {/* Send / Stop / Voice buttons — matching ChatForm styles */}
                        <div className="absolute bottom-0 right-3 flex gap-2 items-center">
                            {/* Voice input (Speech to Text) */}
                            {showVoice && (
                                <SpeechToTextComponent
                                    disabled={disabled}
                                    onChange={(e) => {
                                        const newText = (text || "") + e;
                                        setText(newText);
                                    }}
                                />
                            )}

                            {/* Stop or Send button — same styles as ChatForm SendButton/StopButton */}
                            {isStreaming ? (
                                <button
                                    type="button"
                                    className="rounded-full bg-primary p-1 text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:text-text-secondary disabled:opacity-10"
                                    onClick={onStop}
                                    aria-label="Stop generating"
                                >
                                    <svg
                                        width="24"
                                        height="24"
                                        viewBox="0 0 24 24"
                                        fill="none"
                                        xmlns="http://www.w3.org/2000/svg"
                                        className="icon-lg text-surface-primary"
                                    >
                                        <rect
                                            x="7"
                                            y="7"
                                            width="10"
                                            height="10"
                                            rx="1.25"
                                            fill="currentColor"
                                        />
                                    </svg>
                                </button>
                            ) : (
                                <button
                                    type="button"
                                    onClick={handleSend}
                                    disabled={
                                        !text?.trim() ||
                                        disabled ||
                                        fileUploading
                                    }
                                    className="rounded-full bg-primary p-1 text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:text-text-secondary disabled:opacity-10 bg-gradient-to-b from-[#143BFF] to-[#99BCFF]"
                                    aria-label="Send message"
                                    data-testid="send-button"
                                >
                                    <SendIcon size={24} />
                                </button>
                            )}
                        </div>

                        {/* Toolbar */}
                        <div className="absolute bottom-0 left-3 flex gap-2 items-center">
                            <LinsiTools tools={linsightTools} setTools={setLinsightTools} />
                        </div>
                    </div>
                </div>

                {/* 气泡 */}
                <div
                    className={cn(
                        "absolute w-[calc(100%-2rem)] left-4 rounded-b-[28px] pt-10 -bottom-6 flex justify-between",
                        "bg-gradient-to-b from-[#DEE8FF] via-[#DEE8FF] to-[rgba(222,232,255,0.4)]",
                        "backdrop-blur-sm", // 添加毛玻璃效果
                        "transition-[opacity,transform] duration-500 ease-[cubic-bezier(0.4,0,0.2,1)]",
                        "border border-opacity-10 border-[#143BFF]", // 添加边框和阴影
                        isLingsi ? "opacity-100" : "opacity-0 pointer-events-none",
                        isLingsi ? "translate-y-0" : "translate-y-2" // 整体轻微上浮
                    )}
                    style={{ zIndex: 0 }}
                >
                    <p
                        className={cn(
                            "py-2.5 px-1.5 text-sm text-[#6C7EC5] flex items-center",
                            "transition-all duration-300 ease-out delay-200",
                            "rounded-full mx-4", // 文字背景
                            isLingsi
                                ? "translate-y-0 opacity-100"
                                : "-translate-y-3 opacity-0"
                        )}
                    >
                        <div className="relative h-3.5 mr-4">
                            <div className="size-1.5 rounded-full bg-[#4A5AA1] absolute -left-1 top-0"></div>
                            <div className="w-0.5 h-3 bg-[#4A5AA1] absolute -rotate-45"></div>
                            <div className="size-1.5 rounded-full bg-[#4A5AA1] absolute bottom-0 left-0.5"></div>
                        </div>
                        {localize("com_linsight_tagline")}
                    </p>
                    {bsConfig?.linsight_invitation_code && (
                        <div className="flex gap-4 items-center pr-6">
                            <span className="text-xs text-gray-500">
                                {localize("com_linsight_remaining_times", { count })}
                            </span>
                            {!count && (
                                <Button
                                    size="sm"
                                    className="h-6 text-xs"
                                    onClick={() => setShowCode?.(true)}
                                >
                                    {localize("com_linsight_activate")}
                                </Button>
                            )}
                        </div>
                    )}
                </div>

            </div>
        );
    }
);

LinsightChatInput.displayName = "LinsightChatInput";

export default LinsightChatInput;
