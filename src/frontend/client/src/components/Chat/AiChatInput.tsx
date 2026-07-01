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
import { useNavigate } from "react-router-dom";
import { useRecoilValue, useRecoilState } from "recoil";
import { File_Accept } from "~/common";
import { SkillSelector } from "~/components/Linsight/Input/SkillSelector";
import { taskModeSkillsState } from "~/store/linsight";
import AgentToolSelector from "~/components/Chat/Input/AgentToolSelector";
import { ChatToolDown } from "~/components/Chat/Input/ChatFormTools";
import { ChatKnowledge } from "~/components/Chat/Input/ChatKnowledge";
import { AttachmentBar } from "~/components/Chat/Input/AttachmentBar";
import { TaskModeToggle } from "~/components/Linsight/Input/TaskModeToggle";
import DragDropOverlay from "~/components/Chat/Input/Files/DragDropOverlay";
import { ArrowDown } from "lucide-react";
import { SendIcon } from "~/components/svg";
import { Button, TextareaAutosize } from "~/components/ui";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import InputFiles from "~/pages/appChat/components/InputFiles";
import { useFileDropAndPaste } from "~/pages/appChat/useFileDropAndPaste";
import { bishengConfState } from "~/pages/appChat/store/atoms";
import { checkIfScrollable, cn, removeFocusRings } from "~/utils";
import AiModelSelect from "./AiModelSelect";

export interface AiChatInputFeatures {
    modelSelect?: boolean;
    knowledgeBase?: boolean;
    tools?: boolean;
    fileUpload?: boolean;
    voiceInput?: boolean;
    /** F035 Track H: show the task-mode entry (daily chat surface only). */
    taskModeEntry?: boolean;
    /** F035 Track H: this input IS the task-mode landing. Adds the "添加技能"
     *  entry to the "+" menu; everything else mirrors the daily input. */
    taskMode?: boolean;
}

interface AiChatInputProps {
    size?: '' | 'mini';
    features?: AiChatInputFeatures;
    disabled?: boolean;
    /**
     * F035: disable only the send button while keeping the textarea editable.
     * Used by chat-embedded task mode: a running round must not accept a new
     * submission, but the user may still type the next round's prompt ahead.
     */
    sendDisabled?: boolean;
    isStreaming?: boolean;
    /**
     * F035: a linsight task round is executing. The handoff SSE stream already
     * closed (so ``isStreaming`` is false), but the task keeps running via the
     * worker/WS — show the stop button (wired to terminate-execute) and keep the
     * task-mode toggle highlighted. The textarea stays editable (unlike
     * ``isStreaming``) so the user can compose the next round's prompt.
     */
    taskRunning?: boolean;
    modelOptions?: any[];
    modelValue?: any;
    hasMessages?: boolean;
    /**
     * Landing-page only: render the soft drop shadow (Figma 12669:66966).
     * In-conversation inputs sit flush above the message list, so they keep
     * the border but drop the shadow.
     */
    elevated?: boolean;
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
    /**
     * Landing page coordination: fires whenever the attachment bar's presence
     * changes (kb / file / skill mounted or cleared) so the parent can hide the
     * welcome subtitle while keeping the title + input box positions fixed.
     */
    onSelectionPresenceChange?: (hasSelection: boolean) => void;
    /**
     * F035: toggle task mode in place (no route jump). When provided, the
     * task-mode entry / toggle / skill-pick call this instead of navigating, so
     * the daily welcome page (/c) can own task mode as local state. When absent,
     * the legacy navigate fallback is used (the /linsight Sop usage relies on it).
     */
    onToggleTaskMode?: () => void;
}

const AiChatInput = memo(
    ({
        size = '',
        features,
        disabled = false,
        sendDisabled = false,
        isStreaming = false,
        taskRunning = false,
        modelOptions,
        modelValue,
        placeholder = '',
        hasMessages,
        elevated = false,
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
        onSelectionPresenceChange,
        onToggleTaskMode,
    }: AiChatInputProps) => {
        const {
            modelSelect = true,
            knowledgeBase = true,
            tools = true,
            fileUpload = true,
            voiceInput = true,
            // Off by default: AiChatInput is reused by other surfaces (e.g.
            // Subscription AiAssistantPanel) that must not expose task mode.
            taskModeEntry = false,
            taskMode = false,
        } = features ?? {};

        // Upload size limit comes from /api/v1/env (Recoil bishengConfState),
        // not /api/v1/workstation/config. bsConfig does not carry this field,
        // so reading it from bsConfig would silently fall back to 50MB.
        const envConfig = useRecoilValue(bishengConfState);

        // F035 (PRD §4.1.3): daily "+ → 添加 Skill" picks a skill into the fresh
        // task session ('new'), then enters task mode (/linsight/new) where the
        // selection is refilled as a chip. Keyed 'new' to match the landing page.
        const [dailySkills, setDailySkills] = useRecoilState(taskModeSkillsState('new'));

        // Exiting task mode discards the skill selection so the panel's checkboxes
        // reset in sync with the (now-hidden) skill chips. Track the previous value
        // to fire only on a true→false transition, not on mount or re-entry.
        const prevTaskModeRef = useRef(taskMode);
        useEffect(() => {
            if (prevTaskModeRef.current && !taskMode) {
                setDailySkills((prev) => (prev.length ? [] : prev));
            }
            prevTaskModeRef.current = taskMode;
        }, [taskMode, setDailySkills]);

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
        const [uploadingFiles, setUploadingFiles] = useState<Array<{ id: string; name: string }>>([]);
        const inputFilesRef = useRef<any>(null);

        // Voice input: check if ASR model is available
        const { data: modelData } = useGetWorkbenchModelsQuery();
        const showVoice = voiceInput && !!modelData?.asr_model?.id;

        // Show file upload feature
        const showUpload = fileUpload && bsConfig?.fileUpload?.enabled;

        // F035 (v2.6): the 添加技能 entry is hidden until admin enables it in
        // 工作台-技能管理. Absent on legacy deployments → treated as disabled.
        const showAddSkill = !!bsConfig?.skillEntry?.enabled;

        // v2.5: daily chat always runs through the LangGraph Agent flow. Tools,
        // knowledge bases and files coexist freely — there's no mutex anymore.
        // `agentMode` stays around only so Lingsi / legacy renderers keep working.
        const agentMode = Array.isArray(bsConfig?.tools) && bsConfig.tools.length > 0;
        const kbDisabled = !!disabled;
        const toolsDisabled = !!disabled;
        const filesDisabled = !!disabled;

        const navigate = useNavigate();

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
            if ((!trimmed && !chatFiles?.length) || disabled || sendDisabled || isStreaming || fileUploading) return;
            // Pass files through to parent
            onSend(trimmed, chatFiles);
            setText("");
            setChatFiles(null);
            setUploadingFiles([]);
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
        }, [text, disabled, sendDisabled, isStreaming, fileUploading, onSend, chatFiles, setText]);

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

        const hasSelectionTags = ((selectedOrgKbs && selectedOrgKbs.length > 0) || (chatFiles && chatFiles.length > 0) || uploadingFiles.length > 0 || (taskMode && dailySkills.length > 0)) && !isLingsi;

        // Tell the landing page whether the attachment bar is present so it can
        // hide/show the welcome subtitle without shifting the title or input box.
        // useLayoutEffect (not useEffect) so the subtitle hides in the SAME paint
        // the attachment bar appears — otherwise the block is one frame too tall
        // (bar shown + subtitle still visible) and the whole hero visibly jumps.
        useLayoutEffect(() => {
            onSelectionPresenceChange?.(hasSelectionTags);
        }, [hasSelectionTags, onSelectionPresenceChange]);

        return (
            <div className="px-4 sm:px-0 pb-1 touch-mobile:px-0 touch-mobile:pb-1 shrink-0 relative">
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

                {/* Mounted knowledge spaces / files — a gray strip stacked ABOVE the
                    input box (Figma 12841:47449). The strip overlaps the box by 16px
                    (= the box's corner radius) via -mb-4, so the white box's rounded
                    top corner reaches the edge exactly at the strip's bottom → the
                    left/right edges read as one continuous line ("连下来"), with the
                    white box appearing to emerge from the gray strip. The strip's
                    visible height (62 − 16 = 46px) matches the hidden subtitle's
                    footprint, so the title / input box stay put. */}
                {hasSelectionTags && (
                    <AttachmentBar
                        uploadingFiles={uploadingFiles}
                        files={chatFiles || []}
                        kbs={selectedOrgKbs}
                        skills={taskMode ? dailySkills : []}
                        onRemoveFile={(file) => {
                            inputFilesRef.current?.removeByName?.(file.name);
                            setChatFiles((prev) => (prev || []).filter((i) => i.name !== file.name));
                        }}
                        onRemoveKb={onSelectedOrgKbsChange ? (kb) => {
                            onSelectedOrgKbsChange(selectedOrgKbs.filter((i) => i.id !== kb.id));
                        } : undefined}
                        onRemoveSkill={(skill) => setDailySkills(dailySkills.filter((s) => s.name !== skill.name))}
                    />
                )}

                <div
                    className={cn(
                        // Figma 12669:66966 — white surface, 16px radius, hairline
                        // border (replaces the legacy gray fill). z-[1] keeps it
                        // painted above the attachment strip it overlaps.
                        "relative z-[1] flex w-full flex-col items-start gap-0 overflow-hidden rounded-2xl border border-[#ECECEC] bg-white p-3",
                        // Soft drop shadow on the landing page (always) and on the
                        // in-conversation input only while it has a mounted knowledge
                        // space / file; otherwise in-conversation inputs stay flat
                        // against the message list.
                        (elevated || hasSelectionTags) && "shadow-[0_0_8px_rgba(3,7,117,0.05)]",
                    )}
                >
                    {/* File upload area: file list only. Upload entry lives in the
                        "+" menu; keep the picker trigger hidden here. */}
                    {showUpload && (() => {
                        const InputFilesAny = InputFiles as any;
                        const baseAccept = bsConfig?.enable_etl4lm ? File_Accept.Linsight_Etl4lm : File_Accept.Linsight;
                        // Workstation (daily) chat also accepts OFD. Linsight shares this
                        // enum but is out of scope, so only extend the non-Lingsi path.
                        const accept = isLingsi ? baseAccept : `${baseAccept},.ofd`;
                        return <InputFilesAny
                            ref={inputFilesRef}
                            v={""}
                            showVoice={showVoice}
                            accepts={accept}
                            disabled={filesDisabled}
                            hideTrigger
                            hideList
                            uploadMode={isLingsi ? 'linsight' : 'workstation'}
                            size={envConfig?.uploaded_files_maximum_size || 50}
                            onFilesStateChange={(currentFiles: any[] = []) => {
                                const pending = currentFiles
                                    .filter((f) => f?.isUploading)
                                    .map((f) => ({ id: String(f.id), name: String(f.name || "") }));
                                setUploadingFiles(pending);
                            }}
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
                        rows={1}
                        style={{ height: 52, overflowY: isTextareaScrollable ? "auto" : "hidden" }}
                        className={cn(
                            "m-0 w-full resize-none bg-transparent text-sm mb-2.5 pb-0 pt-0",
                            "placeholder:text-[#999999]",
                            "max-h-[240px] scrollbar-gutter-stable",
                            size === 'mini' ? 'min-h-0' : 'min-h-12',
                            removeFocusRings,
                            "transition-[max-height] duration-200",
                            isTextareaScrollable && "scroll-on-scroll"
                        )}
                    />

                    <div className="flex h-7 min-h-7 w-full min-w-0 items-center justify-between gap-1 touch-mobile:gap-0.5">
                        {/* Toolbar：flex-1 + overflow-hidden，避免与右侧语音/发送横向重叠 */}
                        <div className="input-bottom-left flex min-w-0 flex-1 items-center gap-1 touch-mobile:-ml-1 touch-mobile:gap-1 touch-mobile:pl-0 overflow-hidden">
                            {/* "+" menu — v2.5: combines file upload + knowledge space +
                                org knowledge base. Renders in place of ChatKnowledge when
                                agent mode is active (which is the v2.5 default). */}
                            {!isLingsi && onSelectedOrgKbsChange && (
                                <ChatKnowledge
                                    variant="plus"
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
                                    showFileUpload={showUpload}
                                    fileUploadDisabled={filesDisabled}
                                    onFileUploadClick={() => inputFilesRef.current?.openPicker?.()}
                                    // Task mode toggle present in both modes (plan-mode style).
                                    // Gated by the caller's taskModeEntry feature (role permission in
                                    // ChatView); the legacy global `linsight_entry` switch was retired
                                    // when task mode replaced 灵思 mode, so it no longer gates here.
                                    showTaskModeEntry={taskModeEntry || taskMode}
                                    onEnterTaskMode={onToggleTaskMode ? onToggleTaskMode : () => navigate(taskMode ? '/c/new' : '/linsight/new')}
                                    taskModeActive={taskMode}
                                    skillSelected={taskMode && dailySkills.length > 0}
                                    renderSkillSubmenu={showAddSkill ? () => (
                                        <SkillSelector
                                            selected={dailySkills}
                                            onChange={(next) => {
                                                setDailySkills(next);
                                                // Keep the panel open on toggle (matches the
                                                // knowledge-space panel); it closes on outside click.
                                                // Picking a skill ENTERS task mode only when not
                                                // already in it. onToggleTaskMode is a toggle, so
                                                // calling it while already active would flip it OFF —
                                                // selecting a skill must never exit task mode.
                                                if (taskMode) return;
                                                // Daily welcome page enters in place (callback);
                                                // otherwise navigate to the linsight landing.
                                                if (onToggleTaskMode) onToggleTaskMode();
                                                else navigate('/linsight/new');
                                            }}
                                        />
                                    ) : undefined}
                                />
                            )}
                            {/* Knowledge-space pill — separate "+"-menu sibling that
                                hosts only the knowledge-space / org-knowledge submenus. */}
                            {!isLingsi && onSelectedOrgKbsChange && (
                                <ChatKnowledge
                                    variant="knowledge"
                                    config={bsConfig}
                                    disabled={!!disabled}
                                    value={selectedOrgKbs}
                                    onChange={(val) => {
                                        onSelectedOrgKbsChange(val);
                                        if (val.length > 0 && !agentMode) {
                                            setChatFiles(null);
                                            onSearchTypeChange?.("");
                                        }
                                    }}
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
                            {/* Task-mode toggle — sits to the right of the tools
                                block; clicking exits task mode (flips the local
                                state in place; falls back to navigate for the
                                legacy /linsight Sop usage). */}
                            {taskMode && (
                                <TaskModeToggle
                                    active
                                    onClick={onToggleTaskMode ? onToggleTaskMode : () => navigate('/c/new')}
                                />
                            )}
                        </div>

                        {/* Send / Stop / Voice — 固定宽度列，不参与挤压 */}
                        <div className="flex shrink-0 items-center gap-1.5 touch-mobile:gap-1">
                            {/* Model select */}
                            {modelSelect && modelOptions && !isLingsi && (
                                <AiModelSelect
                                    disabled={!!disabled}
                                    value={modelValue}
                                    options={modelOptions}
                                    onChange={onModelChange!}
                                />
                            )}
                            {isStreaming || taskRunning ? (
                                <button
                                    type="button"
                                    className="btn-brand-primary rounded-full bg-primary p-1 text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:bg-[#E5E6EB] disabled:text-[#86909C] disabled:opacity-100"
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
                            ) : showVoice && !text?.trim() ? (
                                // Empty input → voice button (default); typing any
                                // text flips it to the send button below.
                                <SpeechToTextComponent
                                    disabled={disabled}
                                    onChange={(e) => {
                                        const newText = (text || "") + e;
                                        setText(newText);
                                    }}
                                />
                            ) : (
                                <button
                                    type="button"
                                    onClick={handleSend}
                                    disabled={
                                        !text?.trim() ||
                                        disabled ||
                                        sendDisabled ||
                                        fileUploading
                                    }
                                    className="btn-brand-primary flex h-8 w-8 items-center justify-center rounded-full bg-primary text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:bg-[#E5E6EB] disabled:text-[#86909C] disabled:opacity-100 [&>svg]:text-white disabled:[&>svg]:text-[#4E5969]"
                                    aria-label="Send message"
                                    data-testid="send-button"
                                >
                                    <SendIcon size={18} />
                                </button>
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
