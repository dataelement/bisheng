/**
 * F035 Track H (P2): unified task-mode input shell (spec §1).
 * Layout: textarea on top; toolbar below —
 *   [+] [knowledge v] [tools v] [task-mode toggle]  ...  [model v] [mic/send]
 * Submits through the existing protocol: setLinsightSubmission('new', {...})
 * with the model selector value in the `model` field. Voice input is a
 * placeholder this iteration (toast only).
 * Session-level memory (PRD §4.1.2): knowledge / tools / files live in a
 * per-session Recoil atom and survive exiting task mode; skills are cleared
 * on exit. Exit = navigate back to /c.
 */
import { Outlined } from 'bisheng-icons';
import { Square } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useRecoilState, useRecoilValue } from 'recoil';
import { checkFileParseStatus } from '~/api/linsight';
import { File_Accept, NotificationSeverity } from '~/common';
import DragDropOverlay from '~/components/Chat/Input/Files/DragDropOverlay';
import { TextareaAutosize } from '~/components/ui';
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from '~/components/ui/AlertDialog';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { useLocalize } from '~/hooks';
import { useLinsightSessionManager } from '~/hooks/useLinsightManager';
import InputFiles from '~/pages/appChat/components/InputFiles';
import { useFileDropAndPaste } from '~/pages/appChat/useFileDropAndPaste';
import { bishengConfState } from '~/pages/appChat/store/atoms';
import { useToastContext } from '~/Providers';
import {
    taskModeContextState,
    taskModeSkillsState,
    type TaskModeKnowledgeItem,
    type TaskModeSkill,
    type TaskModeToolItem,
} from '~/store/linsight';
import { cn, removeFocusRings } from '~/utils';
import { ContextChips } from './ContextChips';
import { KnowledgeSpaceSelect } from './KnowledgeSpaceSelect';
import { ModelSelector } from './ModelSelector';
import { PlusMenu } from './PlusMenu';
import { TaskModeToggle } from './TaskModeToggle';
import { ToolsSelect } from './ToolsSelect';

interface TaskModeInputProps {
    /** Session key for per-session memory; 'new' for a fresh task. */
    conversationId?: string;
    disabled?: boolean;
    /**
     * F035 multi-turn: when provided (execution view), a send is a follow-up
     * turn in the CURRENT conversation — routed to /workbench/continue (same
     * session_version + agent thread, context preserved) instead of creating a
     * new session. Absent on the landing page, where a send starts a new task.
     */
    onFollowUp?: (question: string) => void;
    /**
     * Active execution: the task is running (IN_PROGRESS / parked). When true and
     * onStop is provided, the action button morphs into a Stop button (the only
     * stop affordance once the task leaves the queue). Absent on the landing page.
     */
    running?: boolean;
    /** Terminate the running task (reuses the WS hook's stop()). */
    onStop?: () => void;
}

export function TaskModeInput({ conversationId = 'new', disabled = false, onFollowUp, running = false, onStop }: TaskModeInputProps) {
    const localize = useLocalize();
    const navigate = useNavigate();
    const location = useLocation();
    const { showToast } = useToastContext();
    const { data: bsConfig } = useGetBsConfig();
    // Upload size limit lives in /api/v1/env (bishengConfState), not bsConfig.
    const envConfig = useRecoilValue(bishengConfState);

    const sessionKey = conversationId || 'new';
    const [context, setContext] = useRecoilState(taskModeContextState(sessionKey));
    const [skills, setSkills] = useRecoilState(taskModeSkillsState(sessionKey));

    const [text, setText] = useState('');
    const [model, setModel] = useState('');
    const [confirmStopOpen, setConfirmStopOpen] = useState(false);
    const [fileUploading, setFileUploading] = useState(false);
    const [uploadingFiles, setUploadingFiles] = useState<{ id: string; name: string }[]>([]);
    const textAreaRef = useRef<HTMLTextAreaElement>(null);
    const inputFilesRef = useRef<any>(null);

    const { setLinsightSubmission } = useLinsightSessionManager('new');

    // Seed the tool list from admin config; keep the user's per-session checked
    // state for tools that still exist (session memory).
    useEffect(() => {
        if (!bsConfig) return;
        const available = (bsConfig as any).linsightConfig?.tools || [];
        setContext((prev) => {
            const prevChecked = new Map(prev.tools.map((t) => [String(t.id), t.checked]));
            const next: TaskModeToolItem[] = available.map((tool: any) => ({
                id: tool.id,
                name: tool.name,
                checked: prevChecked.has(String(tool.id)) ? prevChecked.get(String(tool.id))! : true,
                data: tool,
            }));
            const unchanged =
                next.length === prev.tools.length &&
                next.every((t, i) => t.id === prev.tools[i]?.id && t.checked === prev.tools[i]?.checked);
            return unchanged ? prev : { ...prev, tools: next };
        });
    }, [bsConfig, setContext]);

    // Drag & paste upload support
    const { isDragging, handlePaste } = useFileDropAndPaste({
        enabled: !disabled,
        onFilesReceived: (files: FileList | File[]) => {
            inputFilesRef.current?.upload(files);
        },
    });

    const filesParsing = context.files.some((file: any) => {
        const status = file?.parsing_status || 'pending';
        return file?.file_id && !['completed', 'failed'].includes(status);
    });

    // Poll parse status for files still being parsed (same contract as the
    // legacy LinsightChatInput); failed files are removed with a toast.
    useEffect(() => {
        const pending = context.files.filter((file: any) => {
            const status = file?.parsing_status || 'pending';
            return file?.file_id && !['completed', 'failed'].includes(status);
        });
        if (!pending.length) return;

        const intervalId = window.setInterval(async () => {
            try {
                const res = await checkFileParseStatus(pending.map((file: any) => file.file_id));
                const statusList = Array.isArray(res.data) ? res.data.filter(Boolean) : [];
                const statusMap = new Map(statusList.map((item: any) => [item.file_id, item.parsing_status]));
                if (!statusMap.size) return;

                inputFilesRef.current?.updateParsingStatus?.(statusMap);

                setContext((prev) => {
                    let changed = false;
                    const nextFiles = prev.files.reduce((result: any[], file: any) => {
                        const nextStatus = statusMap.get(file?.file_id);
                        if (!nextStatus) {
                            result.push(file);
                        } else if (nextStatus === 'failed') {
                            changed = true;
                            showToast({
                                message: localize('com_file_parse_failed_auto_removed', {
                                    0: file.filename || file.file_name || file.name,
                                }),
                                severity: NotificationSeverity.ERROR,
                            });
                        } else if (nextStatus !== file.parsing_status) {
                            changed = true;
                            result.push({ ...file, parsing_status: nextStatus });
                        } else {
                            result.push(file);
                        }
                        return result;
                    }, []);
                    return changed ? { ...prev, files: nextFiles } : prev;
                });
            } catch (error) {
                console.error('Task-mode file parsing status check failed:', error);
            }
        }, 2000);

        return () => window.clearInterval(intervalId);
    }, [context.files, localize, setContext, showToast]);

    // Exit task mode: skills are cleared; knowledge / tools / files stay in the
    // per-session atom and refill on re-entry (PRD §4.1.2).
    const handleExitTaskMode = useCallback(() => {
        setSkills([]);
        navigate('/c/new');
    }, [navigate, setSkills]);

    const clearInputAfterSend = useCallback(() => {
        setText('');
        setContext((prev) => ({ ...prev, files: [] }));
        setUploadingFiles([]);
        inputFilesRef.current?.clear();
        if (textAreaRef.current) textAreaRef.current.style.height = 'auto';
    }, [setContext]);

    const handleSend = useCallback(() => {
        const trimmed = text.trim();
        if ((!trimmed && !context.files.length) || disabled || fileUploading || filesParsing) return;

        // F035 multi-turn: in the execution view a send continues the current
        // conversation (same session_version + agent thread, context kept) rather
        // than spawning a new session. Follow-up turns are text-only for now.
        if (onFollowUp) {
            if (!trimmed) return;
            onFollowUp(trimmed);
            clearInputAfterSend();
            return;
        }

        // convertTools (useLinsightManager) maps the pseudo 'pro_knowledge' entry
        // to org_knowledge_enabled; concrete tools ride along via `data`.
        const submissionTools = [
            { id: 'pro_knowledge', name: localize('com_tools_org_knowledge'), checked: context.knowledge.length > 0 },
            ...context.tools,
        ];

        setLinsightSubmission('new', {
            isNew: true,
            files: context.files.map((item: any) => ({
                file_id: item.file_id,
                file_name: item.filename || item.file_name || item.name,
                parsing_status: item.parsing_status || 'completed',
            })),
            question: trimmed,
            tools: submissionTools as any,
            // Model selector value rides along with the submission (F035).
            model,
            skills: skills.map((s) => s.name),
            enableWebSearch: false,
            useKnowledgeBase: context.knowledge.length > 0,
            // F035: continue the current session on follow-up rounds. conversationId
            // is the real session id in the execution view, 'new' on the landing page.
            sessionId: conversationId && conversationId !== 'new' ? conversationId : undefined,
        });

        setText('');
        setContext((prev) => ({ ...prev, files: [] }));
        setUploadingFiles([]);
        inputFilesRef.current?.clear();
        if (textAreaRef.current) textAreaRef.current.style.height = 'auto';
        if (!location.pathname.includes('/linsight')) navigate('/linsight/new');
    }, [
        text, context, disabled, fileUploading, filesParsing, model, skills,
        localize, location.pathname, navigate, setContext, setLinsightSubmission, conversationId,
        onFollowUp, clearInputAfterSend,
    ]);

    const handleKeyDown = useCallback(
        (e: KeyboardEvent<HTMLTextAreaElement>) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
            }
        },
        [handleSend],
    );

    const handleRemoveKnowledge = (item: TaskModeKnowledgeItem) =>
        setContext((prev) => ({
            ...prev,
            knowledge: prev.knowledge.filter((i) => !(i.id === item.id && i.type === item.type)),
        }));

    const handleRemoveSkill = (skill: TaskModeSkill) =>
        setSkills((prev) => prev.filter((s) => s.name !== skill.name));

    const handleRemoveFile = (file: any) => {
        inputFilesRef.current?.removeByName?.(file.name || file.filename);
        setContext((prev) => ({
            ...prev,
            files: prev.files.filter((i: any) => (i.file_id || i.name) !== (file.file_id || file.name)),
        }));
    };

    const hasText = !!text.trim();
    const accept = (bsConfig as any)?.enable_etl4lm ? File_Accept.Linsight_Etl4lm : File_Accept.Linsight;
    const InputFilesAny = InputFiles as any;

    return (
        <div className="relative shrink-0">
            {isDragging && <DragDropOverlay />}

            <div className="relative flex w-full flex-col rounded-3xl border border-blue-400 bg-gradient-to-b from-[#F2F5FF] to-white p-3 touch-mobile:rounded-2xl">
                {/* Hidden uploader: picker is opened from the "+" menu */}
                <InputFilesAny
                    ref={inputFilesRef}
                    v={''}
                    accepts={accept}
                    hideTrigger
                    hideList
                    uploadMode="linsight"
                    size={(envConfig as any)?.uploaded_files_maximum_size || 50}
                    onFilesStateChange={(currentFiles: any[] = []) => {
                        setUploadingFiles(
                            currentFiles
                                .filter((f) => f?.isUploading)
                                .map((f) => ({ id: String(f.id), name: String(f.name || '') })),
                        );
                    }}
                    onChange={(files: any) => {
                        setFileUploading(!files);
                        setContext((prev) => ({ ...prev, files: files || [] }));
                    }}
                />

                {/* Context chips: skills / knowledge / files (tools never chip) */}
                <ContextChips
                    skills={skills}
                    knowledge={context.knowledge}
                    files={context.files}
                    uploadingFiles={uploadingFiles}
                    onRemoveSkill={handleRemoveSkill}
                    onRemoveKnowledge={handleRemoveKnowledge}
                    onRemoveFile={handleRemoveFile}
                />

                {/* Textarea */}
                <TextareaAutosize
                    ref={textAreaRef}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onPaste={handlePaste}
                    disabled={disabled}
                    placeholder={
                        (bsConfig as any)?.linsightConfig?.input_placeholder ||
                        localize('com_linsight_input_placeholder')
                    }
                    tabIndex={0}
                    data-testid="task-mode-input"
                    rows={2}
                    style={{ height: 64, overflowY: 'auto' }}
                    className={cn(
                        'm-0 mb-2 w-full resize-none bg-transparent text-sm',
                        'placeholder-black/50 dark:placeholder-white/50',
                        'max-h-60 min-h-14 pt-1',
                        removeFocusRings,
                    )}
                />

                {/* Toolbar */}
                <div className="flex h-8 min-h-8 w-full min-w-0 items-center justify-between gap-1">
                    <div className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
                        <PlusMenu
                            disabled={disabled}
                            onUploadFile={() => inputFilesRef.current?.openPicker?.()}
                            taskModeActive
                            onToggleTaskMode={handleExitTaskMode}
                            selectedSkills={skills}
                            onSkillsChange={setSkills}
                            // F035 (v2.6): Add-Skill entry stays hidden unless admin enabled it.
                            showAddSkill={!!bsConfig?.skillEntry?.enabled}
                        />
                        <KnowledgeSpaceSelect
                            value={context.knowledge}
                            disabled={disabled}
                            onChange={(knowledge) => setContext((prev) => ({ ...prev, knowledge }))}
                        />
                        <ToolsSelect
                            tools={context.tools}
                            disabled={disabled}
                            onChange={(tools) => setContext((prev) => ({ ...prev, tools }))}
                        />
                        <TaskModeToggle active disabled={disabled} onClick={handleExitTaskMode} />
                    </div>

                    <div className="flex shrink-0 items-center gap-1.5">
                        <ModelSelector value={model} disabled={disabled} onChange={setModel} />
                        {running && onStop ? (
                            // Active execution: the only stop affordance once the
                            // task leaves the queue. Intentionally NOT gated by
                            // `disabled` (which greys the textarea while running) —
                            // the stop button must stay clickable.
                            <button
                                type="button"
                                onClick={() => setConfirmStopOpen(true)}
                                className="flex size-8 items-center justify-center rounded-full bg-gray-700 text-white transition-all duration-200 hover:bg-gray-800"
                                aria-label={localize('com_linsight_stop')}
                                data-testid="stop-button"
                            >
                                <Square size={14} className="fill-current" />
                            </button>
                        ) : hasText ? (
                            <button
                                type="button"
                                onClick={handleSend}
                                disabled={disabled || fileUploading || filesParsing}
                                className="flex size-8 items-center justify-center rounded-full bg-gradient-to-b from-blue-500 to-blue-200 text-white transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-40"
                                aria-label="Send message"
                                data-testid="send-button"
                            >
                                <Outlined.ArrowUp size={16} />
                            </button>
                        ) : (
                            <button
                                type="button"
                                onClick={() =>
                                    showToast({
                                        message: localize('com_linsight_voice_coming_soon'),
                                        severity: NotificationSeverity.INFO,
                                    })
                                }
                                disabled={disabled}
                                className="flex size-8 items-center justify-center rounded-full bg-gradient-to-b from-blue-500 to-blue-200 text-white transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-40"
                                aria-label={localize('com_linsight_voice_coming_soon')}
                            >
                                {/* Voice input is a visual placeholder this iteration */}
                                <Outlined.Microphone size={16} />
                            </button>
                        )}
                    </div>
                </div>
            </div>

            {/* Stop confirmation: terminating sets the session TERMINATED and
                cannot be resumed, so confirm before discarding in-progress work. */}
            <AlertDialog open={confirmStopOpen} onOpenChange={setConfirmStopOpen}>
                <AlertDialogContent className="max-w-sm">
                    <AlertDialogHeader>
                        <AlertDialogTitle className="text-[16px]">
                            {localize('com_linsight_stop_confirm_title')}
                        </AlertDialogTitle>
                        <AlertDialogDescription>
                            {localize('com_linsight_stop_confirm_desc')}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel>{localize('com_ui_cancel')}</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={() => {
                                setConfirmStopOpen(false);
                                onStop?.();
                            }}
                        >
                            {localize('com_linsight_stop_confirm_ok')}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
