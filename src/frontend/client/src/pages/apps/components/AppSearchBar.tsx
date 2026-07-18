import { useCallback, useEffect, useRef, useState } from 'react';
import { ExpandableSearchField } from '~/components/ui/ExpandableSearchField';
import { useLocalize, useMediaQuery } from '~/hooks';

interface AppSearchBarProps {
  query: string;
  onSearch: (value: string) => void;
  /** Debounce delay in ms, default 300 */
  debounceMs?: number;
  /** Force expanded mode regardless of breakpoint */
  forceExpanded?: boolean;
}

/** Breakpoint aligned with app center header `max-[576px]` — mobile uses always-expanded search */
const APP_SEARCH_MOBILE_MQ = '(max-width: 576px)';

/**
 * 应用中心 / 探索页搜索：桌面端可收起图标搜索；移动端始终展开全宽 + 防抖。
 */
export function AppSearchBar({ query, onSearch, debounceMs = 300, forceExpanded = false }: AppSearchBarProps) {
  const localize = useLocalize();
  const isMobileLayout = useMediaQuery(APP_SEARCH_MOBILE_MQ);
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
      alwaysExpanded={forceExpanded || isMobileLayout}
      showClearButton={forceExpanded || isMobileLayout}
      value={localValue}
      onChange={handleChange}
      placeholder={localize('com_app_search_placeholder')}
      titleWhenCollapsed={localize('com_app_search_by_name')}
      expandedWidthClassName={
        isMobileLayout ? 'w-full min-w-0' : 'w-[220px]'
      }
    />
  );
}
