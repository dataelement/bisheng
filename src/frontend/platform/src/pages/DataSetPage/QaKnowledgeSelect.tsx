import { useSelectLabels } from '@/components/bs-comp/formFields/useSelectLabels';
import { readFileLibDatabase } from '@/controllers/API';
import { showApiError } from '@/controllers/request';
import { Select, type SelectOption } from '@bisheng/ui';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

interface QaKnowledgeSelectProps {
    value: SelectOption[];
    error: boolean;
    onChange: (options: SelectOption[]) => void;
}

export function QaKnowledgeSelect({ value, error, onChange }: QaKnowledgeSelectProps) {
    const { t } = useTranslation();
    const selectLabels = useSelectLabels();
    const [open, setOpen] = useState(false);
    const [keyword, setKeyword] = useState('');
    const query = useInfiniteQuery({
        queryKey: ['dataset', 'qa-knowledge', keyword],
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

    return <Select
        {...selectLabels}
        id="knowledgeLib"
        aria-label={t('dataset.selectQaKnowledgeLib')}
        multiple
        showSearch
        status={error ? 'error' : 'default'}
        value={value.map(option => option.value)}
        options={options}
        placeholder={t('build.selectKnowledgeBase')}
        open={open}
        onOpenChange={next => {
            setOpen(next);
            if (!next) setKeyword('');
        }}
        onSearch={setKeyword}
        onLoadMore={() => {
            if (query.hasNextPage && !query.isFetching) void query.fetchNextPage();
        }}
        loading={query.isInitialLoading}
        loadingMore={query.isFetchingNextPage}
        onChange={(_values, selectedOptions) => onChange(selectedOptions)}
    />;
}
