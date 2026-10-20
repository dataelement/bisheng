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
import { buildChatAccept, isFileNameAccepted } from "~/common/chatAccept";
import { taskModeSkillsState } from "~/store/linsight";
import { useDefaultCheckedSkills } from "~/components/Linsight/Input/useDefaultCheckedSkills";
import { ChatSkillSelector } from "./Input/ChatSkillSelector";
import { ChatResourceMenu } from "~/components/Chat/Input/ChatResourceMenu";
import { skillCenterPreviewEnabled } from "~/components/Skills/types";
import { ComposerEditor } from "./Input/ComposerEditor";
import { useComposerReferences } from "./Input/useComposerReferences";
import { handleComposerResourceKeyDown } from "./Input/composerResourceKeyboard";
import { AttachmentBar } from "~/components/Chat/Input/AttachmentBar";
import DragDropOverlay from "~/components/Chat/Input/Files/DragDropOverlay";
import { Outlined } from "bisheng-icons";
import { ArrowDown } from "lucide-react";
import { Button } from "~/components/ui";
import SpeechToTextComponent from "~/components/Voice/SpeechToText";
import { useContainerCompact, TOOLBAR_COMPACT_THRESHOLD } from "~/hooks";
import { useGetWorkbenchModelsQuery } from "~/hooks/queries/data-provider";
import useLocalize from "~/hooks/useLocalize";
import { useToastContext } from "~/Providers";
import InputFiles from "~/pages/appChat/components/InputFiles";
import { resolveUploadSizeLimits } from "~/pages/knowledge/knowledgeUtils";
import { useFileDropAndPaste } from "~/pages/appChat/useFileDropAndPaste";
import { bishengConfState } from "~/pages/appChat/store/atoms";
import { cn, removeFocusRings } from "~/utils";
import AiModelSelect from "./AiModelSelect";
import type { AttachmentAsk } from "./chatAskHandoff";

export interface AiChatInputFeatures {
    modelSelect?: boolean;
    knowledgeBase?: boolean;
    tools?: boolean;
    fileUpload?: boolean;
    voiceInput?: boolean;
    /** F035 Track H: show the task-mode entry (daily chat surface only). */
    taskModeEntry?: boolean;
    /** This input uses the task-mode landing and its skill selections. */
    taskMode?: boolean;
}

/**
 * The subset of an attachment the leave-task-mode cleanup needs: a display name
 * (whichever of the four spellings this list happens to use) and an id to remove
 * it by. Kept structural so it fits both the committed `chatFiles` entries and
 * the in-flight `uploadingFiles` ones.
 */
interface DroppableAttachment {
    clientId?: string;
    id?: string;
    name?: string;
    file_name?: string;
    filename?: string;
}

interface AiChatInputProps {
    size?: '' | 'mini';
    /** Conversation setup choices belong to the new-chat surface. */
    allowConfiguration?: boolean;
    features?: AiChatInputFeatures;
    disabled?: boolean;
    /**
     * F035: disable only the send button while keeping the textarea editable.
     * Used by chat-embedded task mode: a running round must not accept a new
     * submission, but the user may still type the next round's prompt ahead.
     */
    sendDisabled?: boolean;
    isStreaming?: boolean;
    /** True while backend ASR is processing attached media after send. */
    isParsingMedia?: boolean;
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
    /** Programmatic model-value repairs from AiModelSelect (not user picks). */
    onModelAutoChange?: (val: string) => void;
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
     * Landing page only: a question handed over from a module page together with the
     * file it is about (see chatAskHandoff). The input uploads the file, fills in the
     * question and sends by itself once the file is uploaded and parsed.
     */
    attachmentAsk?: AttachmentAsk | null;
    /** The ask was sent, or could not be (upload unavailable / failed). */
    onAttachmentAskDone?: () => void;
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
        allowConfiguration = true,
        features,
        disabled = false,
        sendDisabled = false,
        isStreaming = false,
        isParsingMedia = false,
        taskRunning = false,
        modelOptions,
        modelValue,
        placeholder = '',
        hasMessages,
        elevated = false,
        onModelChange,
        onModelAutoChange,
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
        attachmentAsk,
        onAttachmentAskDone,
    }: AiChatInputProps) => {
        const localize = useLocalize();
        const { showToast } = useToastContext();
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

        // Collapse toolbar labels to icons when the toolbar's own width (not the
        // viewport's) runs short — e.g. once the sidebar opens on a mid-size screen.
        const { ref: toolbarRef } = useContainerCompact(TOOLBAR_COMPACT_THRESHOLD);

        // Selecting a skill picks it into the fresh
        // task session ('new'), then enters task mode (/linsight/new) where the
        // selection is refilled as a chip. Keyed 'new' to match the landing page.
        const [dailySkills, setDailySkills] = useRecoilState(taskModeSkillsState('new'));

        // True while an IME composition is in flight — see handleKeyDown.
        const isComposingRef = useRef(false);
        const prevTaskModeRef = useRef(taskMode);

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
        const textAreaRef = useRef<HTMLDivElement>(null);
        const [isTextareaScrollable, setIsTextareaScrollable] = useState(false);
        /** True only while user is actively scrolling — drives .scroll-on-scroll (see style.css). */
        const [isTextareaScrolling, setIsTextareaScrolling] = useState(false);
        const textareaScrollHideTimerRef = useRef<number | null>(null);

        const updateTextareaScrollable = useCallback(() => {
            const el = textAreaRef.current;
            setIsTextareaScrollable(el ? el.scrollHeight > el.clientHeight : false);
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
        const [uploadingFiles, setUploadingFiles] = useState<Array<{
            id: string;
            clientId?: string;
            name: string;
            previewUrl?: string;
            mediaPreviewUrl?: string;
            mediaCoverUrl?: string;
            cover_filepath?: string;
            mediaDurationSec?: number;
            /** Folder upload: path relative to the picked folder root. */
            relative_path?: string;
        }>>([]);
        const inputFilesRef = useRef<any>(null);
        const supportsVision = modelOptions?.some(
            (model) => String(model.id) === String(modelValue) && model.visual
        );

        // Switching to ordinary chat keeps skills and filters attachments to
        // the formats supported by its document parser.
        // Fires only on a true→false transition, never on mount or re-entry.
        useEffect(() => {
            if (prevTaskModeRef.current && !taskMode) {
                const dailyAccept = buildChatAccept({
                    enableMedia: !!envConfig?.enable_media_upload,
                    enableEtl4lm: !!bsConfig?.enable_etl4lm,
                    enableVision: !isLingsi && !!supportsVision,
                    includeOfd: !isLingsi,
                });
                const isKept = (name: string) => isFileNameAccepted(name || "", dailyAccept);
                const dropped: string[] = [];
                const collect = (f: DroppableAttachment) => {
                    const name = f?.name || f?.file_name || f?.filename || "";
                    if (isKept(name)) return true;
                    dropped.push(name);
                    // Drop it inside InputFiles too, otherwise its own list would keep
                    // re-publishing the file through onFilesStateChange.
                    inputFilesRef.current?.removeByClientId?.(f?.clientId ?? f?.id);
                    return false;
                };
                setChatFiles((prev) => (prev ? prev.filter(collect) : prev));
                setUploadingFiles((prev) => prev.filter(collect));
                if (dropped.length) {
                    showToast?.({
                        message: localize("com_task_mode_files_dropped", { 0: dropped.join("、") }),
                        status: "warning",
                    });
                }
            }
            prevTaskModeRef.current = taskMode;
            // envConfig/bsConfig are read only when the transition fires; leaving them
            // out keeps a config refetch from re-running the cleanup.
            // eslint-disable-next-line react-hooks/exhaustive-deps
        }, [taskMode, supportsVision]);

        // Voice input: check if ASR model is available
        const { data: modelData } = useGetWorkbenchModelsQuery();
        const showVoice = voiceInput && !!modelData?.asr_model?.id;

        // Show file upload feature
        const showUpload = fileUpload && bsConfig?.fileUpload?.enabled;

        // F035 (v2.6): the 添加技能 entry is hidden until admin enables it in
        // 工作台-技能管理. Absent on legacy deployments → treated as disabled.
        const showAddSkill = !!bsConfig?.skillEntry?.enabled;
        useDefaultCheckedSkills({ skillEntryEnabled: showAddSkill, setSkills: setDailySkills });

        // v2.5: daily chat always runs through the LangGraph Agent flow. Tools,
        // knowledge bases and files coexist freely — there's no mutex anymore.
        // `agentMode` stays around only so Lingsi / legacy renderers keep working.
        const agentMode = Array.isArray(bsConfig?.tools) && bsConfig.tools.length > 0;
        const showSkillPicker = !isLingsi && !!onSelectedOrgKbsChange
            && (showAddSkill || skillCenterPreviewEnabled);
        const showToolPicker = allowConfiguration && tools && (agentMode || (!!onSearchTypeChange && !!bsConfig?.webSearch?.enabled));
        const filesDisabled = !!disabled;
        const fileAccept = buildChatAccept({
            enableMedia: !!envConfig?.enable_media_upload,
            enableEtl4lm: !!bsConfig?.enable_etl4lm,
            enableVision: !isLingsi && !!supportsVision,
            includeOfd: !isLingsi,
            taskMode,
        });

        const navigate = useNavigate();

        // Drag & paste file support (only when not disabled by exclusion)
        const { isDragging, handlePaste } = useFileDropAndPaste({
            enabled: showUpload && !disabled && !filesDisabled,
            // Task mode only: a dropped directory is expanded with its tree
            // preserved. Daily chat has no workspace to rebuild a tree in.
            allowFolders: taskMode,
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

        const hasAttachedFiles =
            (chatFiles?.length ?? 0) > 0 || uploadingFiles.length > 0;
        const filesParsing = (chatFiles ?? []).some(
            (file) => file?.parsing_status && !['completed', 'failed'].includes(file.parsing_status),
        );

        const handleSend = useCallback(() => {
            const trimmed = text.trim();
            // Workbench: uploaded files require accompanying text before send.
            if (!trimmed || disabled || sendDisabled || isStreaming || isParsingMedia || fileUploading || filesParsing) return;
            // The selected model may have changed since these files were attached.
            if (chatFiles?.some((file) => !isFileNameAccepted(file.name || file.filename || '', fileAccept))) {
                showToast({ message: localize('com_ui_upload_file_type_error'), status: 'error' });
                return;
            }
            // Pass files through to parent. The local first-frame poster is a blob
            // that this component revokes on the very next line, and it outranks
            // the server cover in the message bubble — so it stops here, and the
            // bubble goes back to `cover_filepath` once parsing produces it.
            onSend(trimmed, chatFiles?.map((file) => (
                file?.mediaCoverUrl?.startsWith('blob:')
                    ? { ...file, mediaCoverUrl: undefined }
                    : file
            )) ?? chatFiles);
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
        }, [text, disabled, sendDisabled, isStreaming, isParsingMedia, fileUploading, filesParsing, fileAccept, onSend, chatFiles, setText, showToast, localize]);

        // ── Handed-over ask (chatAskHandoff): upload its file, then send unattended ──
        const startedAskKeyRef = useRef<string | null>(null);
        const [autoSendAskKey, setAutoSendAskKey] = useState<string | null>(null);
        useEffect(() => {
            if (!attachmentAsk || startedAskKeyRef.current === attachmentAsk.key) return;
            startedAskKeyRef.current = attachmentAsk.key;
            setText(attachmentAsk.text);
            if (!showUpload || !inputFilesRef.current?.upload) {
                // Uploads are switched off for this deployment: leave the question in the
                // box for the user to send rather than sending it stripped of its subject.
                onAttachmentAskDone?.();
                return;
            }
            inputFilesRef.current.upload([attachmentAsk.file]);
            setAutoSendAskKey(attachmentAsk.key);
        }, [attachmentAsk, showUpload, setText, onAttachmentAskDone]);
        useEffect(() => {
            if (!autoSendAskKey) return;
            const ready = (chatFiles?.length ?? 0) > 0 && uploadingFiles.length === 0 && !fileUploading && !filesParsing;
            if (!ready || !text.trim()) return;
            setAutoSendAskKey(null);
            handleSend();
            onAttachmentAskDone?.();
        }, [autoSendAskKey, chatFiles, uploadingFiles.length, fileUploading, filesParsing, text, handleSend, onAttachmentAskDone]);

        const handleKeyDown = useCallback(
            (e: KeyboardEvent<HTMLDivElement>) => {
                // While an IME is composing (拼音 / かな / 한글), Enter belongs to the
                // IME: it commits the candidate into the box. Sending on it shipped
                // the raw pinyin instead. The event must also pass through
                // untouched — preventDefault here would swallow the commit.
                // `isComposing` misbehaves in Safari and some IMEs only report the
                // legacy 229 keyCode, so every signal is consulted.
                const composing =
                    isComposingRef.current ||
                    e.nativeEvent.isComposing ||
                    e.key === "Process" ||
                    e.keyCode === 229;
                if (e.key === "Enter" && !e.shiftKey && !composing) {
                    e.preventDefault();
                    if (isStreaming) return;
                    handleSend();
                }
            },
            [handleSend, isStreaming]
        );

        // Mirrors useTextarea's guard: true between compositionstart and
        // compositionend, which is the only reliable signal on the browsers where
        // `isComposing` is not.
        const handleCompositionStart = useCallback(() => {
            isComposingRef.current = true;
        }, []);
        const handleCompositionEnd = useCallback(() => {
            isComposingRef.current = false;
        }, []);

        // Skills and knowledge spaces render as references in the writing area.
        const mountedSkills = !isLingsi ? dailySkills : [];
        const { references, onReferencesChange } = useComposerReferences(
            mountedSkills, isLingsi ? [] : selectedOrgKbs, setDailySkills, onSelectedOrgKbsChange,
        );
        const hasMountedKbs = ((!!(selectedOrgKbs && selectedOrgKbs.length > 0) && !isLingsi) || mountedSkills.length > 0);
        const hasInlineAttachments = ((chatFiles && chatFiles.length > 0) || uploadingFiles.length > 0) && !isLingsi;
        const hasSelectionTags = hasMountedKbs || hasInlineAttachments;

        // Tell the landing page whether the attachment bar is present so it can
        // hide/show the welcome subtitle without shifting the title or input box.
        // useLayoutEffect (not useEffect) so the subtitle hides in the SAME paint
        // the attachment bar appears — otherwise the block is one frame too tall
        // (bar shown + subtitle still visible) and the whole hero visibly jumps.
        useLayoutEffect(() => {
            onSelectionPresenceChange?.(hasSelectionTags);
        }, [hasSelectionTags, onSelectionPresenceChange]);

        return (
            <div className="dsh-chat-input-shell px-4 sm:px-0 pb-1 touch-mobile:px-0 touch-mobile:pb-1 shrink-0 relative">
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
                            <span className="text-sm">{localize('dshChat.scrollToBottom')}</span>
                        </Button>
                    </div>
                </div>}

                <div
                    onKeyDownCapture={(event) => handleComposerResourceKeyDown(event, !!disabled || !!isStreaming, isComposingRef.current)}
                    className={cn(
                        // The composer owns its theme surface through dsh-composer-bg.
                        // z-[1] keeps it above the attached resource strip.
                        "dsh-chat-composer relative z-[1] flex w-full flex-col items-start gap-0 overflow-hidden rounded-2xl border border-border-base p-3",
                        // Soft drop shadow on the landing page (always) and on the
                        // in-conversation input only while it has a mounted knowledge
                        // space / file; otherwise in-conversation inputs stay flat
                        // against the message list.
                        (elevated || hasSelectionTags) && "shadow-[0_0_8px_rgba(3,7,117,0.05)]",
                    )}
                >
                    {hasInlineAttachments && (
                        <AttachmentBar
                            uploadingFiles={uploadingFiles}
                            files={chatFiles || []}
                            onRemoveFile={disabled || isStreaming ? undefined : (file) => {
                                // clientId, not name: a folder upload can carry the
                                // same file name in several subdirectories.
                                const id = String(file.clientId ?? file.id);
                                inputFilesRef.current?.removeByClientId?.(id);
                                setUploadingFiles((prev) => prev.filter((item) => String(item.clientId ?? item.id) !== id));
                                setChatFiles((prev) => (prev || []).filter((item) => String(item.clientId ?? item.id) !== id));
                            }}
                        />
                    )}

                    {/* File upload area: file list only. Upload entry lives in the
                        "+" menu; keep the picker trigger hidden here. */}
                    {showUpload && (() => {
                        const InputFilesAny = InputFiles as any;
                        return <InputFilesAny
                            ref={inputFilesRef}
                            v={""}
                            showVoice={showVoice}
                            accepts={fileAccept}
                            disabled={filesDisabled}
                            hideTrigger
                            hideList
                            uploadMode={isLingsi ? 'linsight' : 'workstation'}
                            allowFolderUpload={taskMode}
                            uploadSizeLimits={resolveUploadSizeLimits(envConfig)}
                            size={envConfig?.uploaded_files_maximum_size || 50}
                            onFilesStateChange={(currentFiles: any[] = []) => {
                                const pending = currentFiles
                                    .filter((f) => f?.isUploading)
                                    .map((f) => ({
                                        id: String(f.id),
                                        clientId: String(f.id),
                                        name: String(f.name || ""),
                                        // Drives the folder chip grouping in AttachmentBar.
                                        ...(f.relativePath ? { relative_path: f.relativePath } : {}),
                                        ...(f.previewUrl ? { previewUrl: f.previewUrl } : {}),
                                        ...(f.mediaPreviewUrl ? { mediaPreviewUrl: f.mediaPreviewUrl } : {}),
                                        ...(f.mediaCoverUrl ? { mediaCoverUrl: f.mediaCoverUrl } : {}),
                                        ...(f.cover_filepath ? { cover_filepath: f.cover_filepath } : {}),
                                        ...(f.mediaDurationSec != null ? { mediaDurationSec: f.mediaDurationSec } : {}),
                                    }));
                                setUploadingFiles(pending);

                                const completed = currentFiles
                                    .filter((f) => !f?.isUploading && f?.filePath)
                                    .map((f) => ({
                                        clientId: String(f.id),
                                        file_id: f.fileId || f.id,
                                        filepath: f.filePath,
                                        type: f.type,
                                        name: f.name,
                                        filename: f.name,
                                        file_name: f.name,
                                        // Folder upload: kept for the chip grouping AND threaded
                                        // to the backend so the workspace rebuilds the tree.
                                        relative_path: f.relativePath && f.relativePath !== f.name
                                            ? f.relativePath
                                            : undefined,
                                        size: f.size,
                                        parsing_status: f.parsingStatus || 'completed',
                                        parsingState:
                                            f.parsingStatus && !['completed', 'failed'].includes(f.parsingStatus)
                                                ? 'parsing'
                                                : undefined,
                                        previewUrl: f.previewUrl,
                                        mediaPreviewUrl: f.mediaPreviewUrl,
                                        mediaCoverUrl: f.mediaCoverUrl,
                                        cover_filepath: f.cover_filepath,
                                        mediaDurationSec: f.mediaDurationSec,
                                    }));
                                if (completed.length) {
                                    setFileUploading(pending.length > 0);
                                    setChatFiles(completed);
                                }
                            }}
                            onChange={(files: any) => {
                                if (files === null) {
                                    setFileUploading(true);
                                    return;
                                }
                                setFileUploading(false);
                                setChatFiles(files?.length ? files : []);
                                // Legacy mutex: adding files clears kb + tools.
                                // Agent mode keeps them independent so the model can use everything.
                                if (files && files.length > 0 && !agentMode) {
                                    onSelectedOrgKbsChange?.([]);
                                    onSearchTypeChange?.("");
                                }
                            }}
                        />;
                    })()}

                    <div className="dsh-composer-writing">
                        <ComposerEditor
                            ref={textAreaRef}
                            value={text}
                            references={references}
                            onReferencesChange={onReferencesChange}
                            onChange={setText}
                            onKeyDown={handleKeyDown}
                            onCompositionStart={handleCompositionStart}
                            onCompositionEnd={handleCompositionEnd}
                            onPaste={handlePaste}
                            onScroll={handleTextareaScroll}
                            disabled={disabled || isStreaming}
                            placeholder={placeholder || (allowConfiguration ? bsConfig?.inputPlaceholder || localize("dshChat.placeholder") : localize("dshChat.followupPlaceholder"))}
                            className={cn(size === 'mini' && 'min-h-0', removeFocusRings,
                                isTextareaScrollable && isTextareaScrolling && 'scroll-on-scroll')}
                        />
                    </div>

                    <div className="dsh-composer-toolbar flex h-7 min-h-7 w-full min-w-0 items-center justify-between gap-1 touch-mobile:gap-0.5">
                        {/* Toolbar：flex-1 + overflow-hidden，避免与右侧语音/发送横向重叠 */}
                        <div ref={toolbarRef} className="input-bottom-left flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
                            {/* Add files and knowledge spaces to the conversation context. */}
                            {!isLingsi && onSelectedOrgKbsChange && (
                                <ChatResourceMenu
                                    availableTools={agentMode ? bsConfig.tools : undefined}
                                    showTools={!!showToolPicker && agentMode}
                                    showWebSearch={!!showToolPicker && !agentMode}
                                    webSearchActive={searchType === "netSearch"}
                                    onWebSearchChange={(active) => {
                                        onSearchTypeChange?.(active ? "netSearch" : "");
                                        if (active) {
                                            setChatFiles(null);
                                            onSelectedOrgKbsChange?.([]);
                                        }
                                    }}
                                    showResearch={allowConfiguration && taskModeEntry}
                                    researchActive={taskMode}
                                    onResearchChange={onToggleTaskMode ?? (() => navigate('/c/new'))}
                                    showKnowledgeSelection={knowledgeBase}
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
                                    // Folder upload is task-mode only: daily chat has no agent
                                    // workspace to rebuild the directory tree in.
                                    onFolderUploadClick={taskMode
                                        ? () => inputFilesRef.current?.openFolderPicker?.()
                                        : undefined}
                                >
                                    {/* Skill selection is shared by both platform execution modes. */}
                                    {showSkillPicker ? <ChatSkillSelector menu
                                            selected={dailySkills} disabled={!!disabled}
                                            onChange={setDailySkills} />
                                        : null}
                                </ChatResourceMenu>
                            )}


                        </div>

                        {/* Send / Stop / Voice — 固定宽度列，不参与挤压 */}
                        <div className="dsh-composer-trailing flex shrink-0 items-center gap-1.5 touch-mobile:gap-1">
                            {/* Media parsing hint — sits left of the model select so the
                                send button's disabled state has a visible reason. */}
                            {(isParsingMedia || filesParsing) && (
                                <span className="inline-flex items-center gap-1 whitespace-nowrap text-xs text-primary">
                                    <Outlined.Loading className="size-3.5 animate-spin" />
                                    {localize('com_chat.media_parsing')}
                                </span>
                            )}
                            {/* Model select */}
                            {modelSelect && modelOptions && !isLingsi && (
                                <AiModelSelect
                                    disabled={!!disabled}
                                    value={modelValue}
                                    options={modelOptions}
                                    onChange={onModelChange!}
                                    onAutoChange={onModelAutoChange}
                                />
                            )}
                            {isStreaming || taskRunning ? (
                                <button
                                    type="button"
                                    className="dsh-composer-submit btn-brand-primary rounded-full bg-primary p-1 text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:bg-fill-3 disabled:text-text-3 disabled:opacity-100"
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
                            ) : showVoice && !text?.trim() && !hasAttachedFiles ? (
                                // Empty input → voice button (default); typing any
                                // text flips it to the send button below.
                                // When files are attached, keep the send button visible
                                // (disabled until text is entered).
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
                                        isParsingMedia ||
                                        fileUploading ||
                                        filesParsing
                                    }
                                    className="dsh-composer-submit btn-brand-primary flex h-8 w-8 items-center justify-center rounded-full bg-primary text-text-primary outline-offset-4 transition-all duration-200 disabled:cursor-not-allowed disabled:bg-fill-3 disabled:text-text-3 disabled:opacity-100 [&>svg]:text-white disabled:[&>svg]:text-text-2"
                                    aria-label="Send message"
                                    data-testid="send-button"
                                >
                                    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
                                        <path fill="currentColor" d="M8.3125 0.980183C8.66767 1.0531 8.97902 1.20418 9.2627 1.43233C9.48724 1.61297 9.73029 1.85793 9.97949 2.10714L14.707 6.83468L13.293 8.24874L9 3.95577V15.0417H7V3.95577L2.70703 8.24874L1.29297 6.83468L6.02051 2.10714C6.26971 1.85793 6.51277 1.61297 6.7373 1.43233C6.97662 1.23986 7.28445 1.04402 7.6875 0.980183C7.8973 0.947006 8.1031 0.95516 8.3125 0.980183Z" />
                                    </svg>
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
