import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { readFileLibDatabase } from '@/controllers/API';
import { showApiError } from '@/controllers/request';
import { Select, type SelectOption } from '@bisheng/ui';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface QaKnowledgeSelectProps {
    value: SelectOption[];
    error?: boolean;
    multiple?: boolean;
    className?: string;
    label?: string;
    onChange: (options: SelectOption[]) => void;
}

export function QaKnowledgeSelect({ value, error = false, multiple = true, className, label, onChange }: QaKnowledgeSelectProps) {
    const { t } = useTranslation();
    const selectLabels = useSelectLabels();
    const [open, setOpen] = useState(false);
    const [keyword, setKeyword] = useState('');
    const query = useInfiniteQuery({
        queryKey: ['qa-knowledge-select', keyword],
        queryFn: ({ pageParam = null }) => readFileLibDatabase({
            cursor: pageParam,
            pageSize: 60,
            name: keyword,
            type: 1,
            action: 'use',
        }),
        getNextPageParam: page => page.next_cursor ?? undefined,
        enabled: open,
        cacheTime: 0,
        onError: showApiError,
    });

    const fetchedOptions = query.data?.pages.flatMap(page => page.data
        .filter((item: { id: string | number | null }) => item.id != null && item.id !== '')
        .map((item: { id: string | number; name: string }) => ({ value: item.id, label: item.name }))) ?? [];
    // Keep echoed selections labelled without adding unrelated rows to search results.
    const options = Array.from(new Map(
        [...(keyword ? [] : value), ...fetchedOptions].map(option => [option.value, option]),
    ).values());

    const sharedProps = {
        ...selectLabels,
        id: 'knowledgeLib',
        'aria-label': label || t('dataset.selectQaKnowledgeLib'),
        className,
        showSearch: true,
        status: error ? 'error' as const : 'default' as const,
        options,
        placeholder: t('build.selectKnowledgeBase'),
        open,
        onOpenChange: (next: boolean) => {
            setOpen(next);
            if (!next) setKeyword('');
        },
        onSearch: setKeyword,
        onLoadMore: () => {
            if (query.hasNextPage && !query.isFetching) void query.fetchNextPage();
        },
        loading: query.isInitialLoading,
        loadingMore: query.isFetchingNextPage,
    };

    return multiple
        ? <Select {...sharedProps} multiple value={value.map(option => option.value)}
            onChange={(_values, selectedOptions) => onChange(selectedOptions)} />
        : <Select {...sharedProps} value={value[0]?.value ?? null}
            onChange={(_value, option) => onChange(option ? [option] : [])} />;
}
