import { useCallback, useEffect, useRef, useState } from 'react';
import { ExpandableSearchField } from '~/components/ui/ExpandableSearchField';
import { useLocalize } from '~/hooks';

interface AppSearchBarProps {
  query: string;
  onSearch: (value: string) => void;
  /** Debounce delay in ms, default 300 */
  debounceMs?: number;
}

/**
 * 应用探索页搜索：与消息提醒弹窗同一套可展开搜索 + 防抖；带清空按钮。
 */
export function AppSearchBar({ query, onSearch, debounceMs = 300 }: AppSearchBarProps) {
  const localize = useLocalize();
  const [localValue, setLocalValue] = useState(query);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    setLocalValue(query);
  }, [query]);

  const debouncedSearch = useCallback(
    (val: string) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        onSearch(val);
      }, debounceMs);
    },
    [onSearch, debounceMs],
  );

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const handleChange = (val: string) => {
    setLocalValue(val);
    if (val === '') {
      if (timerRef.current) clearTimeout(timerRef.current);
      onSearch('');
      return;
    }
    debouncedSearch(val);
  };

  return (
    <ExpandableSearchField
      value={localValue}
      onChange={handleChange}
      placeholder={localize('com_app_search_placeholder')}
      titleWhenCollapsed={localize('com_app_search_by_name')}
      expandedWidthClassName="w-[220px]"
    />
  );
}
