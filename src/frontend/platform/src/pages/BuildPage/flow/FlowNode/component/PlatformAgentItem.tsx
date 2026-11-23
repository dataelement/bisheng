import { Button, Checkbox, Input, Select, Textarea } from '@bisheng/ui';
import { isApiError } from '@bisheng/api-client';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { userContext } from '@/contexts/userContext';
import { getPlatformAgentCapabilities, getPlatformAgents, getPlatformAgentVersion, validatePlatformAgents } from '@/controllers/API/workflow';
import { showApiError } from '@/controllers/request';
import type {
    PlatformAgentBinding,
    PlatformAgentBindings,
    PlatformAgentDirectoryItem,
    PlatformAgentExecutionMode,
    PlatformAgentReference,
    PlatformAgentSchema,
    PlatformAgentVersionItem,
} from '@/types/flow';
import SelectVar from './SelectVar';

interface Props {
    workflowId: string;
    nodeId: string;
    reference: PlatformAgentReference | null;
    bindings: PlatformAgentBindings;
    userPrompt?: string;
    executionMode?: PlatformAgentExecutionMode;
    allowInteraction?: boolean;
    onOptionsChange?: (mode: PlatformAgentExecutionMode, allowInteraction: boolean) => void;
    workflowGraph?: { nodes: { id: string; data: unknown }[]; edges: { source: string; target: string }[] };
    onChange: (reference: PlatformAgentReference | null, bindings: PlatformAgentBindings, outputSchema?: PlatformAgentSchema) => void;
    onValidate: (validate: () => string | false, pending: boolean) => void;
}

interface BindingFieldProps {
    nodeId: string;
    name: string;
    schema: PlatformAgentSchema;
    binding?: PlatformAgentBinding;
    onChange: (binding: PlatformAgentBinding) => void;
    onInvalid: (invalid: boolean) => void;
    onRemove: () => void;
    obsolete: boolean;
}

function BindingField({ nodeId, name, schema, binding, onChange, onInvalid, onRemove, obsolete }: BindingFieldProps) {
    const { t } = useTranslation('flow');
    const labels = useSelectLabels();
    const source = binding?.source ?? 'constant';
    const value = binding?.source === 'constant' && 'value' in binding ? binding.value : undefined;
    const [text, setText] = useState(() => value === undefined ? '' : schema.type === 'string' ? String(value) : JSON.stringify(value));
    const [invalid, setInvalid] = useState(false);
    useEffect(() => {
        setText(value === undefined ? '' : schema.type === 'string' ? String(value) : JSON.stringify(value));
    }, [value, schema.type]);
    const handleCommit = (nextText: string) => {
        try {
            const parsed: unknown = schema.type === 'string' ? nextText : JSON.parse(nextText);
            setInvalid(false);
            onInvalid(false);
            onChange({ source: 'constant', value: parsed });
        } catch {
            setInvalid(true);
            onInvalid(true);
        }
    };
    return <div className="space-y-2">
        <label className="bisheng-label">{name} {schema.type ?? 'JSON'}</label>
        {obsolete && <p role="alert">{t('platformAgent.obsoleteInput')}</p>}
        {binding && <Button variant="text" aria-label={`${name} ${t('platformAgent.removeBinding')}`} onClick={onRemove}>{t('platformAgent.removeBinding')}</Button>}
        <Select {...labels} aria-label={`${name} ${t('platformAgent.source')}`} value={source} options={[
            { value: 'constant', label: t('platformAgent.constant') }, { value: 'variable', label: t('platformAgent.variable') },
        ]} onChange={next => { onInvalid(false); setInvalid(false); onChange(next === 'variable' ? { source: 'variable', variable: '' } : { source: 'constant' }); }} />
        {source === 'variable' ? <div className="space-y-2"><SelectVar nodeId={nodeId} itemKey="input_bindings" onSelect={(node: { id: string }, variable: { value: string }) => onChange({ source: 'variable', variable: `${node.id}.${variable.value}` })}><Button>{t('platformAgent.chooseVariable')}</Button></SelectVar><Input aria-label={name} placeholder={t('platformAgent.variableHint')} value={binding?.source === 'variable' ? binding.variable : ''} onChange={event => onChange({ source: 'variable', variable: event.target.value })} /></div> :
            <Textarea aria-label={name} value={text} status={invalid ? 'error' : 'default'} placeholder={schema.type === 'string' ? t('platformAgent.textHint') : t('platformAgent.jsonHint')}
                onChange={event => { setText(event.target.value); handleCommit(event.target.value); }} />}
        {invalid && <p role="alert">{t('platformAgent.invalidJson')}</p>}
    </div>;
}

function formatVersionLabel(item: Pick<PlatformAgentVersionItem, 'version_id' | 'version'>): string {
    return item.version && item.version !== item.version_id ? `${item.version} (${item.version_id})` : item.version_id;
}

function mergeAgentPages(pages?: { data: PlatformAgentDirectoryItem[] }[]): PlatformAgentDirectoryItem[] {
    if (!pages?.length) return [];
    const byId = new Map<string, PlatformAgentDirectoryItem>();
    for (const page of pages) {
        for (const row of page.data ?? []) {
            if (typeof row.agent_id !== 'string' || !row.agent_id) continue;
            let entry = byId.get(row.agent_id);
            if (!entry) {
                entry = {
                    agent_id: row.agent_id,
                    name: row.name || row.agent_id,
                    description: row.description,
                    versions: [],
                    version_items: [],
                };
                byId.set(row.agent_id, entry);
            }
            const rawItems: PlatformAgentVersionItem[] = row.version_items?.length
                ? row.version_items
                : (row.versions ?? []).map(version_id => ({ version_id }));
            for (const item of rawItems) {
                if (typeof item.version_id !== 'string' || !item.version_id) continue;
                if (!entry.versions.includes(item.version_id)) {
                    entry.versions.push(item.version_id);
                    entry.version_items!.push(item);
                }
            }
        }
    }
    return [...byId.values()];
}

export function PlatformAgentItem({ workflowId, nodeId, reference, bindings, userPrompt, executionMode = 'sync', allowInteraction = false,
    onOptionsChange, workflowGraph, onChange, onValidate }: Props) {
    const { t } = useTranslation('flow');
    const labels = useSelectLabels();
    const { user } = useContext(userContext);
    const tenantId = user?.tenant_id ?? user?.leaf_tenant_id;
    const identity = [user?.tenant_id, user?.leaf_tenant_id, user?.user_id];
    const enabled = Boolean(user?.user_id && workflowId);
    const [search, setSearch] = useState('');
    const [currentReference, setCurrentReference] = useState<PlatformAgentReference | null>(reference);
    useEffect(() => {
        setCurrentReference(reference);
    }, [reference]);
    const [invalidFields, setInvalidFields] = useState<Record<string, boolean>>({});
    const [changed, setChanged] = useState(false);
    const callbacks = useRef({ onChange, onValidate, reference: currentReference, bindings });
    callbacks.current = { onChange, onValidate, reference: currentReference, bindings };
    const capability = useQuery({ queryKey: ['platform-agent-capabilities', ...identity], queryFn: getPlatformAgentCapabilities, enabled, cacheTime: 0 });
    const singleTenant = capability.data?.multi_tenant_enabled === false;
    const tenantReady = (typeof tenantId === 'number' && tenantId > 0) || (tenantId == null && singleTenant);
    const canLoadAgents = enabled && tenantReady && capability.data?.platform_agent_enabled === true;
    const scope = ['platform-agent', tenantId ?? (singleTenant ? 'single-tenant' : null), user?.user_id, workflowId, capability.data?.platform_agent_mode, capability.data?.platform_agent_policy_revision];
    const directory = useInfiniteQuery({
        queryKey: [...scope, 'directory', search.trim()],
        queryFn: ({ pageParam }) => getPlatformAgents(workflowId, {
            page_size: 20,
            search: search.trim() || undefined,
            cursor: pageParam as string | undefined,
        }),
        getNextPageParam: page => (page.has_more && page.next_cursor ? page.next_cursor : undefined),
        enabled: canLoadAgents,
        cacheTime: 0,
        retry: false,
    });
    const resources = useMemo(() => mergeAgentPages(directory.data?.pages), [directory.data?.pages]);
    const agentOptions = useMemo(() => {
        const optionMap = new Map<string, string>(resources.map(row => [row.agent_id, row.name]));
        if (currentReference?.agent_id && !optionMap.has(currentReference.agent_id)) {
            optionMap.set(currentReference.agent_id, currentReference.name || currentReference.agent_id);
        }
        return [...optionMap].map(([value, label]) => ({ value, label }));
    }, [resources, currentReference]);
    const selected = resources.find(row => row.agent_id === currentReference?.agent_id);
    const versionOptions = useMemo(() => {
        const optionMap = new Map<string, string>();
        const list = selected?.version_items ?? [];
        for (const item of list) {
            if (typeof item.version_id === 'string' && item.version_id) {
                optionMap.set(item.version_id, formatVersionLabel(item));
            }
        }
        if (currentReference?.version_id && !optionMap.has(currentReference.version_id)) {
            optionMap.set(
                currentReference.version_id,
                formatVersionLabel({ version_id: currentReference.version_id, version: currentReference.version }),
            );
        }
        return [...optionMap].map(([value, label]) => ({ value, label }));
    }, [selected, currentReference]);
    const version = useQuery({ queryKey: [...scope, 'version', currentReference?.agent_id, currentReference?.version_id],
        queryFn: () => getPlatformAgentVersion(workflowId, currentReference!.agent_id, currentReference!.version_id),
        enabled: canLoadAgents && Boolean(currentReference?.agent_id && currentReference.version_id), cacheTime: 0, staleTime: 0 });
    const canRunAsync = version.data?.supports_async === true && version.data.long_tasks_available === true;
    const isMockMode = capability.data?.platform_agent_mode === 'mock';
    const canInteract = (isMockMode ? (canRunAsync && executionMode === 'async') : true)
        && version.data?.interaction_available === true && version.data.supports_interaction === true
        && version.data.available === true && version.data.can_use === true;
    const node = { id: nodeId, data: { id: nodeId, type: 'platform_agent', group_params: [{ params: [
        { key: 'agent_ref', value: currentReference }, { key: 'input_bindings', value: bindings },
        ...(typeof userPrompt === 'string' && userPrompt ? [{ key: 'user_prompt', value: userPrompt }] : []),
        ...(executionMode === 'async' ? [{ key: 'execution_mode', value: 'async' }] : []),
        ...(allowInteraction ? [{ key: 'allow_interaction', value: true }] : []),
    ] }] } };
    // 画布的选中、位置和尺寸变化不影响节点校验。
    const nodes = workflowGraph?.nodes.map(({ id, data }) => id === nodeId ? node : { id, data }) ?? [];
    if (!nodes.some(item => item.id === nodeId)) nodes.push(node);
    const candidate = {
        nodes,
        edges: workflowGraph?.edges.map(({ source, target }) => ({ source, target })) ?? [],
    };
    const validation = useQuery({ queryKey: [...scope, 'validate', nodeId, candidate], queryFn: () => validatePlatformAgents(workflowId, candidate, nodeId),
        enabled: canLoadAgents && Boolean(version.data) && !Object.values(invalidFields).some(Boolean), cacheTime: 0 });
    const validationPending = Boolean(currentReference?.agent_id && currentReference.version_id)
        && (capability.isInitialLoading || version.isFetching || validation.isFetching);
    useEffect(() => { const error = capability.error || directory.error || version.error || validation.error; if (error) showApiError(error); }, [capability.error, directory.error, version.error, validation.error]);
    useLayoutEffect(() => {
        callbacks.current.onValidate(() => {
            if (validationPending) return t('platformAgent.validating');
            if (allowInteraction && !canInteract) return t('platformAgent.interactionUnsupported');
            return currentReference?.agent_id && currentReference.version_id && version.data?.available && version.data.can_use
                && validation.isSuccess && validation.data.valid && !Object.values(invalidFields).some(Boolean)
                ? false : t('platformAgent.invalidConfiguration');
        }, validationPending);
    }, [currentReference, version.data, validation.isSuccess, validation.data, validationPending, invalidFields, allowInteraction, canInteract, t]);
    useEffect(() => { if (version.data) callbacks.current.onChange(callbacks.current.reference, callbacks.current.bindings, version.data.output_schema); }, [version.data]);
    const directoryErrorCode = isApiError(directory.error) ? directory.error.status_code : null;
    const directoryErrorMessage = directoryErrorCode === 10587
        ? t('platformAgent.tokenInvalid')
        : directoryErrorCode === 10555
            ? t('platformAgent.permissionDenied')
            : directoryErrorCode === 10588
                ? t('platformAgent.rateLimited')
                : t('platformAgent.queryFailed');
    return <div className="nowheel nodrag space-y-3">
        {enabled && capability.data?.platform_agent_enabled && !tenantReady && <p role="alert">{t('platformAgent.identityNotReady')}</p>}
        <Input
            aria-label={t('platformAgent.searchPlaceholder')}
            placeholder={t('platformAgent.searchPlaceholder')}
            value={search}
            disabled={!canLoadAgents}
            onChange={event => setSearch(event.target.value)}
        />
        <Select {...labels} aria-label={t('platformAgent.agent')} placeholder={t('platformAgent.chooseAgent')}
            options={agentOptions} value={currentReference?.agent_id ?? null}
            loading={directory.isInitialLoading} onChange={value => {
                setChanged(Boolean(currentReference));
                const nextAgentId = value ? String(value) : '';
                const picked = resources.find(row => row.agent_id === nextAgentId);
                const nextRef: PlatformAgentReference | null = nextAgentId
                    ? { agent_id: nextAgentId, version_id: '', ...(picked?.name ? { name: picked.name } : {}) }
                    : null;
                setCurrentReference(nextRef);
                onChange(nextRef, bindings);
            }} />
        {directory.hasNextPage && <Button onClick={() => { void directory.fetchNextPage().catch(showApiError); }}>{t('platformAgent.loadMore')}</Button>}
        {directory.error ? <p role="alert">{directoryErrorMessage}</p> : directory.data && !directory.isInitialLoading && resources.length === 0 && <p>{t('platformAgent.empty')}</p>}
        <Select {...labels} aria-label={t('platformAgent.version')} placeholder={t('platformAgent.chooseVersion')}
            options={versionOptions}
            value={currentReference?.version_id || null} onChange={value => {
                if (!currentReference || !value) return;
                const versionId = String(value);
                const pickedVer = selected?.version_items?.find(item => item.version_id === versionId);
                const nextRef: PlatformAgentReference = {
                    ...currentReference,
                    version_id: versionId,
                    ...(pickedVer?.call_id ? { call_id: pickedVer.call_id } : {}),
                    ...(pickedVer?.name || selected?.name ? { name: pickedVer?.name || selected?.name } : {}),
                    ...(pickedVer?.version ? { version: pickedVer.version } : {}),
                };
                setChanged(true);
                setInvalidFields({});
                setCurrentReference(nextRef);
                onChange(nextRef, bindings);
            }} />
        {currentReference && <p className="text-sm">{currentReference.name || currentReference.agent_id} / {currentReference.version || currentReference.version_id}</p>}
        {changed && <p role="status">{t('platformAgent.versionChanged')}</p>}
        {validationPending && <p role="status">{t('platformAgent.validating')}</p>}
        {onOptionsChange && version.data && <div className="space-y-2">
            {(canRunAsync || executionMode === 'async') && <Select {...labels} aria-label={t('platformAgent.executionMode')}
                value={executionMode} options={[
                    { value: 'sync', label: t('platformAgent.syncMode') },
                    { value: 'async', label: t('platformAgent.asyncMode'), disabled: !canRunAsync },
                ]} onChange={value => {
                    if (value === 'sync') onOptionsChange('sync', false);
                    if (value === 'async' && canRunAsync) onOptionsChange('async', allowInteraction);
                }} />}
            <Checkbox label={t('platformAgent.allowInteraction')} checked={allowInteraction}
                disabled={!canInteract && !allowInteraction}
                onCheckedChange={checked => onOptionsChange(executionMode, checked === true && canInteract)} />
            {allowInteraction && !canInteract
                ? <p role="alert">{t('platformAgent.interactionUnsupported')}</p>
                : <p>{t('platformAgent.interactionHint')}</p>}
        </div>}
        {version.data && <>
            {[...new Set([...Object.keys(version.data.input_schema.properties ?? {}), ...Object.keys(bindings)])].map(name => <BindingField nodeId={nodeId} key={`${currentReference?.agent_id}:${currentReference?.version_id}:${name}`} name={name} schema={version.data!.input_schema.properties?.[name] ?? {}} binding={bindings[name]}
                obsolete={!(name in (version.data!.input_schema.properties ?? {})) && version.data!.input_schema.additionalProperties === false}
                onRemove={() => { const next = { ...bindings }; delete next[name]; setInvalidFields(previous => ({ ...previous, [name]: false })); onChange(currentReference, next); }}
                onChange={binding => onChange(currentReference, { ...bindings, [name]: binding })} onInvalid={invalid => setInvalidFields(previous => ({ ...previous, [name]: invalid }))} />)}
            {Object.keys(version.data.output_schema?.properties ?? {}).length > 0 && <>
                <p className="bisheng-label">{t('platformAgent.outputSchema')}</p>
                <pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(version.data.output_schema, null, 2)}</pre>
            </>}
        </>}
        {!validationPending && validation.data && !validation.data.valid && <p role="alert">{t('platformAgent.invalidConfiguration')}</p>}
    </div>;
}
