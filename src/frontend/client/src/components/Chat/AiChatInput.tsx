/**
 * Simplified chat input with configurable toolbar.
 * Features: file upload (InputFiles + drag/paste), voice input (STT),
 * model/knowledge/tools selectors, mutual exclusion for kb/tools/files.
 */
import {
    memo,
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
    type KeyboardEvent,
} from "react";
import { File_Accept } from "~/common";
import AgentToolSelector from "~/components/Chat/Input/AgentToolSelector";
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
import { checkIfScrollable, cn, removeFocusRings } from "~/utils";
import AiModelSelect from "./AiModelSelect";
import BooksIcon from "../ui/icon/Books";
import BookOpen from "../ui/icon/BookOpen";

/** 超出该字数则省略；省略后为「前 5 字 + …」共 6 个显示单位（与产品规则一致） */
const KB_TAG_MAX_CHARS = 5;

function formatKbTagLabel(name: string): string {
    const chars = Array.from(name);
    if (chars.length <= KB_TAG_MAX_CHARS) return name;
    return `${chars.slice(0, KB_TAG_MAX_CHARS).join("")}\u2026`;
}

const KbTag = ({ kb, onRemove }: { kb: any; onRemove?: () => void }) => {
    const label = formatKbTagLabel(kb.name ?? "");
    return (
        <div className="group flex h-6 min-w-0 max-w-[160px] shrink-0 items-center rounded-[4px] bg-white px-2 text-xs text-slate-700 transition-colors duration-200 hover:bg-slate-50">
            {kb.type === 'space' ? (
                <BookOpen className="mr-1 size-4 shrink-0 text-[#999]" />
            ) : (
                <BooksIcon className="mr-1 size-4 shrink-0 text-[#999]" />
            )}

            <span className="min-w-0 flex-1 truncate text-left" title={kb.name}>
                {label}
            </span>
            {onRemove && (
                <button
                    type="button"
                    onClick={onRemove}
                    className="ml-0.5 flex size-4 shrink-0 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-200"
                    aria-label="Remove"
                >
                    ✕
                </button>
            )}
        </div>
    );
};

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
        const [isTextareaScrollable, setIsTextareaScrollable] = useState(false);
        /** True only while user is actively scrolling — drives .scroll-on-scroll (see style.css). */
        const [isTextareaScrolling, setIsTextareaScrolling] = useState(false);
        const textareaScrollHideTimerRef = useRef<number | null>(null);

        const updateTextareaScrollable = useCallback(() => {
            const el = textAreaRef.current;
            setIsTextareaScrollable(el ? checkIfScrollable(el) : false);
        }, []);

        const handleTextareaScroll = useCallback(() => {
            if (!isTextareaScrollable) return;
            setIsTextareaScrolling(true);
            if (textareaScrollHideTimerRef.current) {
                window.clearTimeout(textareaScrollHideTimerRef.current);
            }
            textareaScrollHideTimerRef.current = window.setTimeout(() => {
                setIsTextareaScrolling(false);
                textareaScrollHideTimerRef.current = null;
            }, 700);
        }, [isTextareaScrollable]);

        useLayoutEffect(() => {
            const id = requestAnimationFrame(() => updateTextareaScrollable());
            return () => cancelAnimationFrame(id);
        }, [text, updateTextareaScrollable]);

        useEffect(() => {
            if (!isTextareaScrollable) {
                setIsTextareaScrolling(false);
            }
        }, [isTextareaScrollable]);

        useEffect(() => {
            return () => {
                if (textareaScrollHideTimerRef.current) {
                    window.clearTimeout(textareaScrollHideTimerRef.current);
                }
            };
        }, []);

        // File upload state
        const [fileUploading, setFileUploading] = useState(false);
        const [chatFiles, setChatFiles] = useState<any[] | null>(null);
        const inputFilesRef = useRef<any>(null);

        // Voice input: check if ASR model is available
        const { data: modelData } = useGetWorkbenchModelsQuery();
        const showVoice = voiceInput && !!modelData?.asr_model?.id;

        // Show file upload feature
        const showUpload = fileUpload && bsConfig?.fileUpload?.enabled;

        // v2.5: daily chat always runs through the LangGraph Agent flow. Tools,
        // knowledge bases and files coexist freely — there's no mutex anymore.
        // `agentMode` stays around only so Lingsi / legacy renderers keep working.
        const agentMode = Array.isArray(bsConfig?.tools) && bsConfig.tools.length > 0;
        const kbDisabled = !!disabled;
        const toolsDisabled = !!disabled;
        const filesDisabled = !!disabled;

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
            setIsTextareaScrollable(false);
            setIsTextareaScrolling(false);
            if (textareaScrollHideTimerRef.current) {
                window.clearTimeout(textareaScrollHideTimerRef.current);
                textareaScrollHideTimerRef.current = null;
            }
        }, [text, disabled, isStreaming, fileUploading, onSend, chatFiles, setText]);

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
            <div className="px-4 sm:px-0 pb-4 max-[575px]:px-0 max-[575px]:pb-3 shrink-0 relative">
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

                <div className={`relative pb-3 flex w-full flex-col bg-surface-tertiary overflow-hidden max-[575px]:bg-[#f4f5f7] ${size === 'mini' ? 'rounded-xl' : 'rounded-3xl max-[575px]:rounded-2xl'}`}>
                    {/* File upload area: file list only. Trigger moves to "+" menu
                        when we're in v2.5 agent mode; legacy flow keeps built-in icon. */}
                    {showUpload && (() => {
                        const InputFilesAny = InputFiles as any;
                        const accept = isLingsi ? (bsConfig?.enable_etl4lm ? File_Accept.Linsight_Etl4lm : File_Accept.Linsight) : "";
                        return <InputFilesAny
                            ref={inputFilesRef}
                            v={""}
                            showVoice={showVoice}
                            accepts={accept}
                            disabled={filesDisabled}
                            hideTrigger={agentMode && !isLingsi}
                            uploadMode={isLingsi ? 'linsight' : 'workstation'}
                            size={bsConfig?.uploaded_files_maximum_size || 50}
                            onChange={(files: any) => {
                                setFileUploading(!files);
                                setChatFiles(files);
                                // Legacy mutex: adding files clears kb + tools.
                                // Agent mode keeps them independent so the model can use everything.
                                if (files && files.length > 0 && !agentMode) {
                                    onSelectedOrgKbsChange?.([]);
                                    onSearchTypeChange?.("");
                                }
                            }}
                        />;
                    })()}

                    {/* Selected knowledge base / space tags */}
                    {selectedOrgKbs && selectedOrgKbs.length > 0 && !isLingsi && (
                        <div className="m-3 max-h-[72px] overflow-y-auto scrollbar-on-hover">
                            <div className="flex flex-wrap gap-1">
                                {selectedOrgKbs.map((kb) => (
                                    <KbTag
                                        key={kb.id}
                                        kb={kb}
                                        onRemove={onSelectedOrgKbsChange ? () => {
                                            onSelectedOrgKbsChange(
                                                selectedOrgKbs.filter((i) => i.id !== kb.id)
                                            );
                                        } : undefined}
                                    />
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
                        onScroll={handleTextareaScroll}
                        onHeightChange={updateTextareaScrollable}
                        disabled={disabled || isStreaming}
                        placeholder={placeholder || bsConfig?.inputPlaceholder}
                        tabIndex={0}
                        data-testid="ai-chat-input"
                        data-scrolling={isTextareaScrollable && isTextareaScrolling ? "true" : "false"}
                        rows={2}
                        style={{ height: 84, overflowY: isTextareaScrollable ? "auto" : "hidden" }}
                        className={cn(
                            "p-3 pb-0 m-0 w-full resize-none bg-transparent text-sm",
                            "placeholder-black/50 dark:placeholder-white/50",
                            "max-h-[240px] pl-4 pr-6 scrollbar-gutter-stable",
                            size === 'mini' ? 'min-h-0' : 'min-h-20',
                            removeFocusRings,
                            "transition-[max-height] duration-200",
                            isTextareaScrollable && "scroll-on-scroll"
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
                            {/* "+" menu — v2.5: combines file upload + knowledge space +
                                org knowledge base. Renders in place of ChatKnowledge when
                                agent mode is active (which is the v2.5 default). */}
                            {!isLingsi && (agentMode || bsConfig?.knowledgeBase?.enabled) && onSelectedOrgKbsChange && (
                                <ChatKnowledge
                                    config={bsConfig}
                                    disabled={!!disabled}
                                    value={selectedOrgKbs}
                                    onChange={(val) => {
                                        onSelectedOrgKbsChange(val);
                                        // Legacy mutex only; agent mode keeps concurrent selections.
                                        if (val.length > 0 && !agentMode) {
                                            setChatFiles(null);
                                            onSearchTypeChange?.("");
                                        }
                                    }}
                                    showFileUpload={showUpload && agentMode}
                                    fileUploadDisabled={filesDisabled}
                                    onFileUploadClick={() => inputFilesRef.current?.openPicker?.()}
                                />
                            )}
                            {/* Model select */}
                            {modelSelect && modelOptions && !isLingsi && (
                                <AiModelSelect
                                    disabled={!!disabled}
                                    value={modelValue}
                                    options={modelOptions}
                                    onChange={onModelChange!}
                                />
                            )}
                            {/* Tools picker */}
                            {tools && agentMode && (
                                <AgentToolSelector
                                    availableTools={bsConfig.tools}
                                    disabled={toolsDisabled}
                                />
                            )}
                            {tools && !agentMode && onSearchTypeChange && (
                                <ChatToolDown
                                    linsi={isLingsi}
                                    config={bsConfig}
                                    searchType={searchType}
                                    setSearchType={(type) => {
                                        onSearchTypeChange(type);
                                        // Legacy mutex: clear files + kb when tool activated
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
