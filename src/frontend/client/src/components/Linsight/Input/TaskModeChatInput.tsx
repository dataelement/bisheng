/**
 * F035 Track H: task-mode landing input.
 *
 * Goal: the task-mode landing (`/linsight/new`) renders the SAME daily-chat
 * input (AiChatInput) as `/c/new` — identical slogan area, toolbar, and buttons,
 * NO blue gradient — differing ONLY by an extra "添加技能" entry in the "+" menu.
 * Task mode = daily mode + a `taskMode` flag (Claude plan-mode style).
 *
 * This wrapper owns the state + submit so the daily AiChatInput stays generic:
 *   - knowledge / tools / files / skills live in the per-session Recoil atoms
 *     (taskModeContextState / taskModeSkillsState) — same as the legacy
 *     TaskModeInput, so session memory (PRD §4.1.2) is preserved.
 *   - onSend builds the linsight submission and calls setLinsightSubmission('new')
 *     which the existing useLinsightSubmit (mounted in Sop) watches and drives
 *     through submit → start-execute → WS. The execution pipeline is untouched.
 *
 * Tools picker: task mode shows the SAME daily tools picker (AgentToolSelector),
 * so it is visually + functionally identical to daily chat. The picker's
 * selection lives in the shared Recoil atom `store.selectedAgentTools` and
 * operates on `bsConfig.tools` (the workstation tool groups). AgentToolSelector
 * already speaks the linsight hierarchical tool shape (parent + selected
 * children), so we wire the user's actual selection straight into the linsight
 * submission (see handleSend) instead of the seeded `context.tools`.
 */
import { useCallback, useEffect } from 'react';
import { useRecoilState, useRecoilValue } from 'recoil';
import AiChatInput from '~/components/Chat/AiChatInput';
import { useLocalize } from '~/hooks';
import { useAuthContext } from '~/hooks/AuthContext';
import { useGetBsConfig } from '~/hooks/queries/data-provider';
import { useGetWorkbenchModelsQuery } from '~/hooks/queries/queries';
import { useLinsightSessionManager } from '~/hooks/useLinsightManager';
import store from '~/store';
import {
    taskModeContextState,
    taskModeSkillsState,
    type TaskModeToolItem,
} from '~/store/linsight';

interface TaskModeChatInputProps {
    /** Session key for per-session memory; 'new' for a fresh task. */
    conversationId?: string;
}

export function TaskModeChatInput({ conversationId = 'new' }: TaskModeChatInputProps) {
    const localize = useLocalize();
    const { data: bsConfig } = useGetBsConfig();

    const sessionKey = conversationId || 'new';
    const [context, setContext] = useRecoilState(taskModeContextState(sessionKey));
    const [skills] = useRecoilState(taskModeSkillsState(sessionKey));
    // Shared with daily mode: a manual pick (manual: true) wins everywhere;
    // otherwise task mode follows the admin's linsight_default_model_id.
    const [chatModel, setChatModel] = useRecoilState(store.chatModel);
    const model = String(chatModel.id || '');

    // Task-mode model resolution: the mode's own manual memory
    // (`bs:{uid}:taskModel`, separate from the daily record) wins; without a
    // valid record the admin-configured linsight_default_model_id applies,
    // falling back to the first option.
    const { user } = useAuthContext();
    const { data: workbenchCfg } = useGetWorkbenchModelsQuery();
    useEffect(() => {
        const models = bsConfig?.models || [];
        if (!models.length || !user?.id) return;
        const key = `bs:${user.id}:taskModel`;
        const savedId = localStorage.getItem(key);
        let manual = true;
        let target = savedId ? models.find((m) => String(m.id) === savedId) : undefined;
        if (!target) {
            manual = false;
            // Stale record (model removed/disabled) — drop it for good.
            if (savedId) localStorage.removeItem(key);
            const raw = (workbenchCfg as Record<string, unknown> | undefined)?.linsight_default_model_id;
            const adminDefaultId =
                typeof raw === 'string' || typeof raw === 'number' ? String(raw) : null;
            target =
                (adminDefaultId ? models.find((m) => String(m.id) === adminDefaultId) : undefined) ??
                models[0];
        }
        if (
            target &&
            (String(target.id) !== String(chatModel.id) || !!chatModel.manual !== manual || chatModel.mode !== 'task')
        ) {
            setChatModel({
                id: Number(target.id),
                name: target.displayName || target.name || '',
                manual,
                mode: 'task',
            });
        }
    }, [chatModel.id, chatModel.manual, chatModel.mode, bsConfig, workbenchCfg, user?.id, setChatModel]);

    // Daily tools picker selection — same shared atom AgentToolSelector writes to.
    const selectedAgentTools = useRecoilValue(store.selectedAgentTools);

    const { setLinsightSubmission } = useLinsightSessionManager('new');

    // Seed the linsight tool list from admin config; preserve the user's
    // per-session checked state for tools that still exist (session memory).
    // Same contract as the legacy TaskModeInput.
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

    const handleSend = useCallback(
        (text: string, files?: any[] | null) => {
            const trimmed = text.trim();
            const fileList = files || [];
            if (!trimmed && !fileList.length) return;

            // convertTools (useLinsightManager) maps the pseudo 'pro_knowledge'
            // entry → org_knowledge_enabled; concrete tools ride along via `data`.
            //
            // Tools come from the user's actual daily-picker selection
            // (selectedAgentTools), NOT the seeded context.tools. Each selected
            // group carries {id, name, description, children:[{id,tool_key,name,desc}]}
            // — exactly what convertTools' `tool.data` path reads, except it also
            // wants `is_preset`, which we recover from bsConfig.tools by id.
            const availableTools: any[] = Array.isArray((bsConfig as any)?.tools)
                ? (bsConfig as any).tools
                : [];
            const presetById = new Map(
                availableTools.map((t: any) => [t.id, t.is_preset]),
            );
            const mappedSelectedTools = selectedAgentTools.map((group) => ({
                id: group.id,
                checked: true,
                data: {
                    id: group.id,
                    name: group.name,
                    is_preset: presetById.get(group.id),
                    description: group.description,
                    children: (group.children || []).map((c) => ({
                        id: c.id,
                        name: c.name,
                        tool_key: c.tool_key,
                        desc: c.desc,
                    })),
                },
            }));
            const submissionTools = [
                {
                    id: 'pro_knowledge',
                    name: localize('com_tools_org_knowledge'),
                    checked: context.knowledge.some((k) => k.type === 'org'),
                },
                ...mappedSelectedTools,
            ];

            setLinsightSubmission('new', {
                isNew: true,
                files: fileList.map((item: any) => ({
                    file_id: item.file_id,
                    file_name: item.filename || item.file_name || item.name,
                    parsing_status: item.parsing_status || 'completed',
                    // Folder upload: the backend rebuilds this tree under the task
                    // workspace's uploads/ prefix. Undefined for a loose file.
                    relative_path: item.relative_path,
                    size: item.size,
                })),
                question: trimmed,
                tools: submissionTools as any,
                // Model selector value rides along with the submission (F035).
                model,
                skills: skills.map((s) => s.name),
                enableWebSearch: false,
                useKnowledgeBase: context.knowledge.length > 0,
                // New session on the landing page.
                sessionId: undefined,
            });
        },
        [context, model, skills, localize, setLinsightSubmission, selectedAgentTools, bsConfig],
    );

    return (
        <AiChatInput
            disabled={!bsConfig?.models?.length}
            // Task mode uses its own input placeholder (daily falls back to
            // bsConfig.inputPlaceholder inside AiChatInput).
            placeholder={(bsConfig as any)?.linsightConfig?.input_placeholder || localize('com_linsight_input_placeholder')}
            features={{
                taskModeEntry: false,
                taskMode: true,
                modelSelect: true,
                knowledgeBase: true,
                // Show the SAME daily tools picker (AgentToolSelector). agentMode
                // turns on automatically inside AiChatInput because bsConfig.tools
                // is a non-empty array, so the AgentToolSelector path renders (not
                // the legacy searchType ChatToolDown). Its selection feeds the
                // linsight submission via store.selectedAgentTools (see handleSend).
                tools: true,
                fileUpload: true,
                voiceInput: true,
            }}
            onScrollToBottom={() => { }}
            modelOptions={bsConfig?.models}
            modelValue={chatModel.id}
            onModelChange={(val) => {
                const picked = bsConfig?.models?.find((m) => String(m.id) === String(val));
                setChatModel({
                    id: Number(val),
                    name: picked?.displayName || '',
                    manual: true,
                    mode: 'task',
                });
                // This page doesn't mount useChatModelMemo — persist the
                // task-mode pick directly.
                if (user?.id) localStorage.setItem(`bs:${user.id}:taskModel`, String(val));
            }}
            onModelAutoChange={(val) => {
                const picked = bsConfig?.models?.find((m) => String(m.id) === String(val));
                setChatModel((prev) => ({
                    id: Number(val),
                    name: picked?.displayName || prev.name || '',
                    manual: prev.manual ?? false,
                    mode: prev.mode,
                }));
            }}
            onSend={handleSend}
            onStop={() => { }}
            bsConfig={bsConfig}
            selectedOrgKbs={context.knowledge}
            onSelectedOrgKbsChange={(val) => setContext((prev) => ({ ...prev, knowledge: val as any }))}
        />
    );
}
