import { Button, Input, Select } from '@bisheng/ui';
import { isApiError } from '@bisheng/api-client';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useContext, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Label } from '@/components/bs-ui/label';
import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { userContext } from '@/contexts/userContext';
import { getPlatformModelCapabilities, listPlatformModels } from '@/controllers/API/platformModel';
import type { PlatformModelReference, PlatformModelSummary } from '@/types/flow/platformModel';

interface Props {
    workflowId: string;
    reference: PlatformModelReference | null;
    required?: boolean;
    onChange: (ref: PlatformModelReference | null) => void;
    onValidate: (validate: () => string | false) => void;
}

function modelOptionKey(item: Pick<PlatformModelReference, 'resource_id' | 'version_id'>): string {
    return `${item.resource_id}::${item.version_id}`;
}

function formatModelLabel(item: Pick<PlatformModelReference, 'name' | 'version' | 'version_id'>): string {
    const base = item.name || item.version_id;
    return item.version ? `${base} (${item.version})` : base;
}

export function PlatformModelSelectItem({ workflowId, reference, required = true, onChange, onValidate }: Props) {
    const { t } = useTranslation('flow');
    const labels = useSelectLabels();
    const { user } = useContext(userContext);
    const [search, setSearch] = useState('');

    const capability = useQuery({
        queryKey: ['platform-llm-capabilities'],
        queryFn: getPlatformModelCapabilities,
        cacheTime: 0,
    });
    const tenant = user?.tenant_id ?? user?.leaf_tenant_id ?? (capability.data?.multi_tenant_enabled === false ? 'single-tenant' : null);
    const enabled = Boolean(user?.user_id && tenant && workflowId && capability.isSuccess && capability.data.platform_llm_enabled);

    const directory = useInfiniteQuery({
        queryKey: ['platform-llm', user?.user_id, tenant, workflowId, search.trim()],
        enabled,
        cacheTime: 0,
        retry: false,
        queryFn: ({ pageParam }) => listPlatformModels(workflowId, {
            page_size: 20,
            search: search.trim() || undefined,
            cursor: pageParam as string | undefined,
        }),
        getNextPageParam: page => (page.has_more && page.next_cursor ? page.next_cursor : undefined),
    });

    const rows: PlatformModelSummary[] = useMemo(
        () => (enabled && directory.isSuccess ? directory.data.pages.flatMap(page => page.items) : []),
        [enabled, directory.isSuccess, directory.data],
    );

    const { options, itemByKey } = useMemo(() => {
        const optionMap = new Map<string, string>();
        const modelMap = new Map<string, PlatformModelSummary>();
        for (const row of rows) {
            if (!row.resource_id || !row.version_id || !row.call_id) continue;
            const key = modelOptionKey(row);
            optionMap.set(key, formatModelLabel(row));
            modelMap.set(key, row);
        }
        // 保留已保存的固定版本引用，列表刷新时不静默改绑其他版本
        if (reference?.resource_id && reference.version_id && reference.call_id) {
            const savedKey = modelOptionKey(reference);
            if (!optionMap.has(savedKey)) {
                optionMap.set(savedKey, formatModelLabel(reference));
            }
        }
        return {
            options: [...optionMap].map(([value, label]) => ({ value, label })),
            itemByKey: modelMap,
        };
    }, [rows, reference]);

    const selectedKey = reference?.resource_id && reference.version_id ? modelOptionKey(reference) : null;
    const validSelection = Boolean(
        reference?.resource_id
        && reference.version_id
        && reference.call_id
        && reference.version_id.toLowerCase() !== 'latest'
        && reference.call_id.toLowerCase() !== 'latest',
    );

    useEffect(() => {
        onValidate(() => {
            if (required && !validSelection) {
                return t('platformLlm.invalidModel');
            }
            return false;
        });
    }, [required, validSelection, onValidate, t]);

    const errorCode = isApiError(directory.error) ? directory.error.status_code : null;
    const errorMessage = errorCode === 10581
        ? t('platformLlm.tokenInvalid')
        : errorCode === 10582
            ? t('platformLlm.permissionDenied')
            : t('platformAgent.queryFailed');

    return (
        <div className="nodrag nowheel space-y-2 mb-4">
            <Label className="flex items-center bisheng-label">
                {required && <span className="text-red-500">*</span>}
                {t('node.platform_llm.model_ref.label')}
            </Label>
            <Input
                aria-label={t('platformLlm.searchPlaceholder')}
                placeholder={t('platformLlm.searchPlaceholder')}
                value={search}
                disabled={!enabled}
                onChange={event => setSearch(event.target.value)}
            />
            <Select
                {...labels}
                aria-label={t('platformLlm.choose')}
                placeholder={t('platformLlm.choose')}
                value={selectedKey}
                options={options}
                loading={directory.isInitialLoading}
                disabled={!enabled}
                onChange={value => {
                    if (!value) {
                        onChange(null);
                        return;
                    }
                    const picked = itemByKey.get(String(value));
                    if (picked) {
                        onChange({
                            resource_id: picked.resource_id,
                            version_id: picked.version_id,
                            call_id: picked.call_id,
                            name: picked.name,
                            version: picked.version,
                        });
                    }
                }}
            />
            {reference?.version_id && (
                <p className="text-xs text-muted-foreground break-all">
                    {t('platformLlm.pinnedVersion')}: {reference.version || reference.version_id}
                </p>
            )}
            {directory.hasNextPage && enabled && (
                <Button onClick={() => { void directory.fetchNextPage(); }}>
                    {t('platformAgent.loadMore')}
                </Button>
            )}
            {(directory.isError || capability.isError) ? (
                <p role="alert" className="text-xs text-red-500">{errorMessage}</p>
            ) : (enabled && directory.data && rows.length === 0) ? (
                <p className="text-xs text-muted-foreground">{t('platformLlm.empty')}</p>
            ) : null}
        </div>
    );
}
