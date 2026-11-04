import { useMemo, useState } from 'react';
import useDebounce from '~/hooks/Input/useDebounce';
import { useGetOrgToolPages } from '~/hooks/queries/data-provider';
import type { BsConfig } from '~/types/chat';
import { KnowledgePickerDialog, type KnowledgePickerSelectionProps } from './KnowledgePickerDialog';

interface KnowledgeBaseDialogProps extends KnowledgePickerSelectionProps {
  configured?: BsConfig['orgKbs'];
}

/** Keep beta5's organization catalog, visibility filtering, ordering and pagination. */
export function KnowledgeBaseDialog({ configured, ...selection }: KnowledgeBaseDialogProps) {
  const [keyword, setKeyword] = useState('');
  const debouncedKeyword = useDebounce(keyword, 500);
  const { data, isFetching, isError, refetch, hasNextPage, fetchNextPage } = useGetOrgToolPages({
    page_size: 20, name: debouncedKeyword, sort_by: 'name',
    preferred_ids: configured?.map(item => String(item.id)).join(',') || '', action: 'visible',
  });
  const items = useMemo(() => {
    const ordered = [...(configured ?? [])].sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0));
    const preferred = new Map(ordered.map((item, index) => [String(item.id), index]));
    const unique = new Map((data?.pages.flatMap(page => page.data) ?? [])
      .filter(item => item.id != null && String(item.id) !== '')
      .map(item => [String(item.id), { ...item, updatedAt: item.update_time }]));
    return [...unique.values()].sort((a, b) =>
      (preferred.get(String(a.id)) ?? Number.MAX_SAFE_INTEGER) - (preferred.get(String(b.id)) ?? Number.MAX_SAFE_INTEGER));
  }, [configured, data]);
  return <KnowledgePickerDialog {...selection} kind="org" keyword={keyword} onKeywordChange={setKeyword}
    groups={items.length ? [{ key: 'org', items }] : []} isFetching={isFetching} isError={isError}
    onRetry={() => { void refetch(); }} hasMore={!!hasNextPage} onLoadMore={() => { void fetchNextPage(); }} />;
}
