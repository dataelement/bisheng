import { Button, Checkbox, Input, Select, Textarea } from '@bisheng/ui';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useContext, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { userContext } from '@/contexts/userContext';
import { getPlatformAgentCapabilities, getPlatformAgents, getPlatformAgentVersion, validatePlatformAgents } from '@/controllers/API/workflow';
import { showApiError } from '@/controllers/request';
import type { PlatformAgentBinding, PlatformAgentBindings, PlatformAgentExecutionMode, PlatformAgentReference, PlatformAgentSchema } from '@/types/flow';
import SelectVar from './SelectVar';

interface Props {
    workflowId: string;
    nodeId: string;
    reference: PlatformAgentReference | null;
    bindings: PlatformAgentBindings;
    executionMode?: PlatformAgentExecutionMode;
    allowInteraction?: boolean;
    onOptionsChange?: (mode: PlatformAgentExecutionMode, allowInteraction: boolean) => void;
    workflowGraph?: { nodes: { id: string; data: unknown }[]; edges: unknown[] };
    onChange: (reference: PlatformAgentReference | null, bindings: PlatformAgentBindings, outputSchema?: PlatformAgentSchema) => void;
    onValidate: (validate: () => string | false) => void;
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

export function PlatformAgentItem({ workflowId, nodeId, reference, bindings, executionMode = 'sync', allowInteraction = false,
    onOptionsChange, workflowGraph, onChange, onValidate }: Props) {
    const { t } = useTranslation('flow');
    const labels = useSelectLabels();
    const { user } = useContext(userContext);
    const tenantId = user?.tenant_id ?? user?.leaf_tenant_id;
    const identity = [user?.tenant_id, user?.leaf_tenant_id, user?.user_id];
    const enabled = Boolean(user?.user_id && workflowId);
    const [invalidFields, setInvalidFields] = useState<Record<string, boolean>>({});
    const [changed, setChanged] = useState(false);
    const callbacks = useRef({ onChange, onValidate, reference, bindings });
    callbacks.current = { onChange, onValidate, reference, bindings };
    const capability = useQuery({ queryKey: ['platform-agent-capabilities', ...identity], queryFn: getPlatformAgentCapabilities, enabled, cacheTime: 0 });
    const singleTenant = capability.data?.multi_tenant_enabled === false;
    const tenantReady = (typeof tenantId === 'number' && tenantId > 0) || (tenantId == null && singleTenant);
    const canLoadAgents = enabled && tenantReady && capability.data?.platform_agent_enabled === true;
    const scope = ['platform-agent', tenantId ?? (singleTenant ? 'single-tenant' : null), user?.user_id, workflowId, capability.data?.platform_agent_mode, capability.data?.platform_agent_policy_revision];
    const directory = useInfiniteQuery({ queryKey: [...scope, 'directory'], queryFn: ({ pageParam }) => getPlatformAgents(workflowId, pageParam as string | undefined),
        getNextPageParam: page => page.next_cursor || undefined, enabled: canLoadAgents, cacheTime: 0 });
    const resources = directory.data?.pages.flatMap(page => page.data).filter(row => typeof row.agent_id === 'string' && row.agent_id.length > 0) ?? [];
    const selected = resources.find(row => row.agent_id === reference?.agent_id);
    const version = useQuery({ queryKey: [...scope, 'version', reference?.agent_id, reference?.version_id],
        queryFn: () => getPlatformAgentVersion(workflowId, reference!.agent_id, reference!.version_id),
        enabled: canLoadAgents && Boolean(reference?.agent_id && reference.version_id), cacheTime: 0, staleTime: 0 });
    const canRunAsync = version.data?.supports_async === true && version.data.long_tasks_available === true;
    const canInteract = canRunAsync && executionMode === 'async' && capability.data?.platform_agent_mode === 'mock'
        && version.data?.interaction_available === true && version.data.supports_interaction === true
        && version.data.available === true && version.data.can_use === true;
    const graph = { nodes: [{ id: nodeId, data: { id: nodeId, type: 'platform_agent', group_params: [{ params: [
        { key: 'agent_ref', value: reference }, { key: 'input_bindings', value: bindings },
        ...(executionMode === 'async' ? [{ key: 'execution_mode', value: 'async' }] : []),
        ...(allowInteraction ? [{ key: 'allow_interaction', value: true }] : []),
    ] }] } }], edges: [] };
    const candidate = workflowGraph ? { ...workflowGraph, nodes: workflowGraph.nodes.map(node => node.id === nodeId ? { ...node, data: graph.nodes[0].data } : node) } : graph;
    const validation = useQuery({ queryKey: [...scope, 'validate', nodeId, candidate], queryFn: () => validatePlatformAgents(workflowId, candidate, nodeId),
        enabled: canLoadAgents && Boolean(version.data) && !Object.values(invalidFields).some(Boolean), cacheTime: 0 });
    useEffect(() => { const error = capability.error || directory.error || version.error || validation.error; if (error) showApiError(error); }, [capability.error, directory.error, version.error, validation.error]);
    useEffect(() => {
        callbacks.current.onValidate(() => {
            if (allowInteraction && !canInteract) return t('platformAgent.interactionUnsupported');
            return reference?.agent_id && reference.version_id && version.data?.available && version.data.can_use
                && validation.data?.valid && !Object.values(invalidFields).some(Boolean) ? false : t('platformAgent.invalidConfiguration');
        });
    }, [reference, version.data, validation.data, invalidFields, allowInteraction, canInteract, t]);
    useEffect(() => { if (version.data) callbacks.current.onChange(callbacks.current.reference, callbacks.current.bindings, version.data.output_schema); }, [version.data]);
    return <div className="nowheel nodrag space-y-3">
        {capability.data?.platform_agent_mode === 'mock' && <p className="bisheng-label">{t('platformAgent.mock')}</p>}
        {enabled && capability.data?.platform_agent_enabled && !tenantReady && <p role="alert">{t('platformAgent.identityNotReady')}</p>}
        <Select {...labels} aria-label={t('platformAgent.agent')} placeholder={t('platformAgent.chooseAgent')}
            options={resources.map(row => ({ value: row.agent_id, label: row.name }))} value={reference?.agent_id ?? null}
            loading={directory.isInitialLoading} onChange={value => { setChanged(Boolean(reference)); onChange(value ? { agent_id: String(value), version_id: '' } : null, bindings); }} />
        {directory.hasNextPage && <Button onClick={() => { void directory.fetchNextPage().catch(showApiError); }}>{t('platformAgent.loadMore')}</Button>}
        {directory.error ? <p role="alert">{t('platformAgent.queryFailed')}</p> : directory.data && !directory.isInitialLoading && resources.length === 0 && <p>{t('platformAgent.empty')}</p>}
        <Select {...labels} aria-label={t('platformAgent.version')} placeholder={t('platformAgent.chooseVersion')}
            options={(selected?.versions ?? []).filter(value => typeof value === 'string' && value.length > 0).map(value => ({ value, label: value }))}
            value={reference?.version_id || null} onChange={value => { if (!reference || !value) return; setChanged(true); setInvalidFields({}); onChange({ ...reference, version_id: String(value) }, bindings); }} />
        {reference && <p className="text-sm">{reference.agent_id} / {reference.version_id}</p>}
        {changed && <p role="status">{t('platformAgent.versionChanged')}</p>}
        {onOptionsChange && version.data && <div className="space-y-2">
            {(canRunAsync || executionMode === 'async') && <Select {...labels} aria-label={t('platformAgent.executionMode')}
                value={executionMode} options={[
                    { value: 'sync', label: t('platformAgent.syncMode') },
                    { value: 'async', label: t('platformAgent.asyncMode') },
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
            {[...new Set([...Object.keys(version.data.input_schema.properties ?? {}), ...Object.keys(bindings)])].map(name => <BindingField nodeId={nodeId} key={`${reference?.agent_id}:${reference?.version_id}:${name}`} name={name} schema={version.data!.input_schema.properties?.[name] ?? {}} binding={bindings[name]}
                obsolete={!(name in (version.data!.input_schema.properties ?? {})) && version.data!.input_schema.additionalProperties === false}
                onRemove={() => { const next = { ...bindings }; delete next[name]; setInvalidFields(previous => ({ ...previous, [name]: false })); onChange(reference, next); }}
                onChange={binding => onChange(reference, { ...bindings, [name]: binding })} onInvalid={invalid => setInvalidFields(previous => ({ ...previous, [name]: invalid }))} />)}
            <p className="bisheng-label">{t('platformAgent.outputSchema')}</p>
            <pre className="whitespace-pre-wrap break-all text-xs">{JSON.stringify(version.data.output_schema, null, 2)}</pre>
        </>}
        {validation.data && !validation.data.valid && <p role="alert">{t('platformAgent.invalidConfiguration')}</p>}
    </div>;
}
