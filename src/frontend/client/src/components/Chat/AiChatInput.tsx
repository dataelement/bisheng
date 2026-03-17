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
    type KeyboardEvent,
} from "react";
import { File_Accept } from "~/common";
import { ChatToolDown } from "~/components/Chat/Input/ChatFormTools";
import { ChatKnowledge } from "~/components/Chat/Input/ChatKnowledge";
import DragDropOverlay from "~/components/Chat/Input/Files/DragDropOverlay";
import { ArrowDown } from "lucide-react";
import { SendIcon } from "~/components/svg";
import { Button, TextareaAutosize } from "~/components/ui";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import InputFiles from "~/pages/appChat/components/InputFiles";
import { useFileDropAndPaste } from "~/pages/appChat/useFileDropAndPaste";
import { cn, removeFocusRings } from "~/utils";
import AiModelSelect from "./AiModelSelect";
import BooksIcon from "../ui/icon/Books";
import BookOpen from "../ui/icon/BookOpen";

export interface AiChatInputFeatures {
    modelSelect?: boolean;
    knowledgeBase?: boolean;
    tools?: boolean;
    fileUpload?: boolean;
    voiceInput?: boolean;
}

interface AiChatInputProps {
    size?: '' | 'mini';
    features?: AiChatInputFeatures;
    disabled?: boolean;
    isStreaming?: boolean;
    modelOptions?: any[];
    modelValue?: any;
    hasMessages?: boolean;
    onModelChange?: (val: string) => void;
    placeholder?: string;
    /** files: uploaded file list [{path, name}], null means still uploading */
    onSend: (text: string, files?: any[] | null) => void;
    onStop: () => void;
    onScrollToBottom: () => void;
    /** Optional controlled value — for filling in preset questions */
    value?: string;
    onChange?: (val: string) => void;
    /** Config for knowledge base and tools */
    bsConfig?: any;
    /** Knowledge base state */
    selectedOrgKbs?: any[];
    onSelectedOrgKbsChange?: (val: any[]) => void;
    /** Search type state (for tools) */
    searchType?: string;
    onSearchTypeChange?: (type: string) => void;
    /** Support Lingsi mode UI differences */
    isLingsi?: boolean;
}

const AiChatInput = memo(
    ({
        size = '',
        features,
        disabled = false,
        isStreaming = false,
        modelOptions,
        modelValue,
        placeholder = '',
        hasMessages,
        onModelChange,
        onSend,
        onStop,
        onScrollToBottom,
        value: externalValue,
        onChange: onExternalChange,
        bsConfig,
        selectedOrgKbs = [],
        onSelectedOrgKbsChange,
        searchType = "",
        onSearchTypeChange,
        isLingsi = false,
    }: AiChatInputProps) => {
        const {
            modelSelect = true,
            knowledgeBase = true,
            tools = true,
            fileUpload = true,
            voiceInput = true,
        } = features ?? {};

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

        // File upload state
        const [fileUploading, setFileUploading] = useState(false);
        const [chatFiles, setChatFiles] = useState<any[] | null>(null);
        const inputFilesRef = useRef<any>(null);

        // Voice input: check if ASR model is available
        const { data: modelData } = useGetWorkbenchModelsQuery();
        const showVoice = voiceInput && !!modelData?.asr_model?.id;

        // Show file upload feature
        const showUpload = fileUpload && bsConfig?.fileUpload?.enabled;

        // --- Mutual exclusion logic ---
        // Each "mode" (kb, tools, files) is active if it has data selected
        const hasKbs = selectedOrgKbs.length > 0;
        const hasToolsActive = searchType === "netSearch";
        const hasFiles = !!chatFiles && chatFiles.length > 0;

        // If any one is active, disable the other two pickers
        const kbDisabled = !!disabled || hasToolsActive || hasFiles;
        const toolsDisabled = !!disabled || hasKbs || hasFiles;
        const filesDisabled = disabled || hasKbs || hasToolsActive;

        // Drag & paste file support (only when not disabled by exclusion)
        const { isDragging, handlePaste } = useFileDropAndPaste({
            enabled: showUpload && !disabled && !filesDisabled,
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

        const handleSend = useCallback(() => {
            const trimmed = text.trim();
            if ((!trimmed && !chatFiles?.length) || disabled || isStreaming || fileUploading) return;
            // Pass files through to parent
            onSend(trimmed, chatFiles);
            setText("");
            setChatFiles(null);
            inputFilesRef.current?.clear();
            // Reset textarea height
            if (textAreaRef.current) {
                textAreaRef.current.style.height = "auto";
            }
        }, [text, disabled, isStreaming, fileUploading, onSend, chatFiles]);

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
            <div className="px-4 pb-4 shrink-0 relative">
                {/* Drag-drop overlay */}
                {isDragging && <DragDropOverlay />}

                {/* Scroll to bottom button — above input */}
                {hasMessages && <div className="absolute -top-10 w-full">
                    <div className="flex justify-center">
                        <Button
                            className="flex items-center h-8 justify-center gap-2 rounded-2xl bg-blue-100 px-4 py-1 font-medium text-blue-main hover:bg-blue-200"
                            onClick={onScrollToBottom}
                        >
                            <ArrowDown className="size-4" />
                            <span className="text-sm">回到底部</span>
                        </Button>
                    </div>
                </div>}

                <div className={`relative pb-3 flex w-full flex-col bg-surface-tertiary overflow-hidden ${size === 'mini' ? 'rounded-xl' : 'rounded-3xl'}`}>
                    {/* File upload area: file list + attachment button */}
                    {showUpload && (() => {
                        const InputFilesAny = InputFiles as any;
                        const accept = isLingsi ? (bsConfig?.enable_etl4lm ? File_Accept.Linsight_Etl4lm : File_Accept.Linsight) : "";
                        return <InputFilesAny
                            ref={inputFilesRef}
                            v={""}
                            showVoice={showVoice}
                            accepts={accept}
                            disabled={filesDisabled}
                            size={bsConfig?.uploaded_files_maximum_size || 50}
                            onChange={(files: any) => {
                                setFileUploading(!files);
                                setChatFiles(files);
                                // When files are added, clear kb and tools
                                if (files && files.length > 0) {
                                    onSelectedOrgKbsChange?.([]);
                                    onSearchTypeChange?.("");
                                }
                            }}
                        />;
                    })()}

                    {/* Selected knowledge base / space tags */}
                    {selectedOrgKbs && selectedOrgKbs.length > 0 && !isLingsi && (
                        <div className="mx-2 mt-2 max-h-[100px] overflow-y-auto">
                            <div className="flex flex-wrap gap-2">
                                {selectedOrgKbs.map((kb) => (
                                    <div
                                        key={kb.id}
                                        className="group relative flex items-center gap-1
                                            px-2 py-1 pr-6
                                            rounded-full bg-white border border-slate-200
                                            text-xs text-slate-700
                                            max-w-[200px]
                                            hover:bg-slate-50 transition-all duration-200"
                                    >
                                        {kb.type === 'space' ? (
                                            <BookOpen
                                                className="size-[14px] text-slate-500 shrink-0"
                                            />
                                        ) : (
                                            <BooksIcon
                                                className="size-[14px] text-slate-500 shrink-0"
                                            />
                                        )}

                                        <span className="truncate flex-1 min-w-0 transition-all duration-200 group-hover:text-[11px]">
                                            {kb.name}
                                        </span>

                                        {onSelectedOrgKbsChange && (
                                            <button
                                                onClick={() => {
                                                    onSelectedOrgKbsChange(
                                                        selectedOrgKbs.filter((i) => i.id !== kb.id)
                                                    );
                                                }}
                                                className="absolute right-1 top-1/2 -translate-y-1/2
                                                    opacity-0 group-hover:opacity-100
                                                    w-4 h-4 flex items-center justify-center
                                                    rounded-full hover:bg-slate-200
                                                    text-slate-400 transition-opacity duration-200"
                                            >
                                                ✕
                                            </button>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {/* Textarea */}
                    <TextareaAutosize
                        ref={textAreaRef}
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        onKeyDown={handleKeyDown}
                        onPaste={handlePaste}
                        disabled={disabled}
                        placeholder={placeholder || bsConfig?.inputPlaceholder}
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
                                    className="rounded-full bg-primary p-1 text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:text-text-secondary disabled:opacity-10"
                                    aria-label="Send message"
                                    data-testid="send-button"
                                >
                                    <SendIcon size={24} />
                                </button>
                            )}
                        </div>

                        {/* Toolbar: model select + knowledge base + tools */}
                        <div className="absolute bottom-0 left-3 flex gap-2 items-center">
                            {/* Model select */}
                            {modelSelect && modelOptions && !isLingsi && (
                                <AiModelSelect
                                    disabled={!!disabled}
                                    value={modelValue}
                                    options={modelOptions}
                                    onChange={onModelChange!}
                                />
                            )}

                            {/* Knowledge base — disabled when tools or files active */}
                            {knowledgeBase &&
                                !isLingsi &&
                                bsConfig?.knowledgeBase?.enabled &&
                                onSelectedOrgKbsChange && (
                                    <ChatKnowledge
                                        config={bsConfig}
                                        disabled={kbDisabled}
                                        value={selectedOrgKbs}
                                        onChange={(val) => {
                                            onSelectedOrgKbsChange(val);
                                            // Clear files when kb is selected
                                            if (val.length > 0) {
                                                setChatFiles(null);
                                                onSearchTypeChange?.("");
                                            }
                                        }}
                                    />
                                )
                            }

                            {/* Tools (web search etc.) — disabled when kb or files active */}
                            {tools && onSearchTypeChange && (
                                <ChatToolDown
                                    linsi={isLingsi}
                                    config={bsConfig}
                                    searchType={searchType}
                                    setSearchType={(type) => {
                                        onSearchTypeChange(type);
                                        // Clear files and kb when tools activated
                                        if (type === "netSearch") {
                                            setChatFiles(null);
                                            onSelectedOrgKbsChange?.([]);
                                        }
                                    }}
                                    disabled={toolsDisabled}
                                />
                            )}
                        </div>
                    </div>
                </div>
            </div>
        );
    }
);

AiChatInput.displayName = "AiChatInput";

export default AiChatInput;
