import { Button, Select } from '@bisheng/ui';
import { isApiError } from '@bisheng/api-client';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useContext, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { userContext } from '@/contexts/userContext';
import { getKnowledgeCapabilities, getPlatformKnowledge, listPlatformKnowledge } from '@/controllers/API/platformKnowledge';
import type { KnowledgeReference } from '@/types/flow/platformKnowledge';

interface Props {
    workflowId: string;
    reference: KnowledgeReference | null;
    onChange: (ref: KnowledgeReference | null) => void;
    onValidate: (validate: () => string | false) => void;
}

export function PlatformKnowledgeSelectItem({ workflowId, reference, onChange, onValidate }: Props) {
    const { t } = useTranslation('flow');
    const labels = useSelectLabels();
    const { user } = useContext(userContext);
    const [selected, setSelected] = useState(reference?.resource_id ?? '');
    const capability = useQuery({
        queryKey: ['platform-knowledge-capabilities'],
        queryFn: getKnowledgeCapabilities,
        cacheTime: 0,
    });
    const tenant = user?.tenant_id ?? user?.leaf_tenant_id ?? (capability.data?.multi_tenant_enabled === false ? 'single-tenant' : null);
    const enabled = Boolean(user?.user_id && tenant && workflowId && capability.isSuccess && capability.data.platform_knowledge_enabled);
    const scope = ['platform-knowledge', user?.user_id, tenant, workflowId, capability.data?.platform_knowledge_mode,
        capability.data?.platform_knowledge_connection_id, capability.data?.platform_knowledge_policy_revision];
    const directory = useInfiniteQuery({
        queryKey: [...scope, 'list'], enabled, cacheTime: 0, retry: false,
        queryFn: ({ pageParam }) => listPlatformKnowledge(workflowId, pageParam),
        getNextPageParam: page => page.next_cursor ?? undefined,
    });
    const detail = useQuery({
        queryKey: [...scope, 'detail', selected], enabled: enabled && Boolean(selected), cacheTime: 0, retry: false,
        queryFn: () => getPlatformKnowledge(workflowId, selected),
    });
    const activeSelection = enabled && detail.isSuccess && detail.data.resource_id === selected && detail.data.status === 'active';
    useEffect(() => {
        onValidate(() => activeSelection ? false : t('platformKnowledge.invalidKnowledge'));
    }, [activeSelection, onValidate, t]);
    const rows = enabled && directory.isSuccess ? directory.data.pages.flatMap(page => page.items) : [];
    const options = new Map(rows.filter(row => row.resource_id && !(detail.isError && row.resource_id === selected))
        .map(row => [row.resource_id, row.name]));
    if (activeSelection) options.set(detail.data.resource_id, detail.data.name);
    const directoryDenied = isApiError(directory.error) && directory.error.status_code === 10564;
    return <div className="nodrag nowheel space-y-2">
        {capability.data?.platform_knowledge_mode === 'mock' && <p className="bisheng-label">{t('platformAgent.mock')}</p>}
        <Select {...labels} aria-label={t('platformKnowledge.choose')}
            placeholder={t('platformKnowledge.choose')} value={selected || null}
            options={[...options].map(([value, label]) => ({ value, label }))}
            loading={directory.isInitialLoading} disabled={!enabled}
            onChange={value => {
                const id = value ? String(value) : '';
                setSelected(id);
                onChange(id ? { resource_id: id } : null);
            }} />
        {directory.hasNextPage && enabled && <Button onClick={() => { void directory.fetchNextPage(); }}>{t('platformAgent.loadMore')}</Button>}
        {directory.isError || capability.isError ? <p role="alert">{t(directoryDenied ? 'api_errors:10564' : 'platformAgent.queryFailed')}</p>
            : enabled && directory.data && !rows.length ? <p>{t('platformKnowledge.empty')}</p> : null}
        {selected && (!enabled || detail.isError) && <p role="alert">{t('platformKnowledge.invalidKnowledge')}</p>}
    </div>;
}
