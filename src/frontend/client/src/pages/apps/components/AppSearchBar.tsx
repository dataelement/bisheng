import { Search, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useMediaQuery } from '~/hooks';
import { cn } from '~/utils';

interface AppSearchBarProps {
  query: string;
  onSearch: (value: string) => void;
  /** Debounce delay in ms, default 300 */
  debounceMs?: number;
}

/**
 * Expandable search bar with built-in debounce.
 * Collapses to an icon when empty + blurred, stays expanded when has content.
 */
export function AppSearchBar({ query, onSearch, debounceMs = 300 }: AppSearchBarProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [localValue, setLocalValue] = useState(query);
  const inputRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();

  const isMobile576 = useMediaQuery('(max-width: 576px)');

  // Keep local value in sync with external query changes
  useEffect(() => {
    setLocalValue(query);
  }, [query]);

  // Debounced search callback
  const debouncedSearch = useCallback(
    (val: string) => {
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        onSearch(val);
      }, debounceMs);
    },
    [onSearch, debounceMs],
  );

  // Cleanup timer on unmount
  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const handleChange = (val: string) => {
    setLocalValue(val);
    debouncedSearch(val);
  };

  const handleClear = () => {
    setLocalValue('');
    onSearch(''); // Clear immediately, no debounce
    inputRef.current?.focus();
  };

  const expanded = isMobile576 ? true : isOpen || !!localValue;

  return (
    <div
      className={cn(
        'flex items-center border border-gray-100 rounded-lg px-3 py-[5px] transition-all duration-200',
        expanded ? (isMobile576 ? 'w-full' : 'w-64') : 'w-8 h-8 justify-center cursor-pointer',
      )}
      onClick={() => {
        if (!expanded && !isMobile576) {
          setIsOpen(true);
          setTimeout(() => inputRef.current?.focus(), 50);
        }
      }}
    >
      <Search size={14} className="text-gray-400 flex-shrink-0" />
      {expanded && (
        <>
          <input
            ref={inputRef}
            autoFocus={!isMobile576}
            value={localValue}
            onChange={(e) => handleChange(e.target.value)}
            className="ml-2 w-full bg-transparent outline-none text-sm"
            placeholder="搜索应用..."
            onBlur={() => {
              if (!isMobile576 && !localValue) setIsOpen(false);
            }}
          />
          {localValue && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleClear();
              }}
              className="text-gray-400 hover:text-gray-600"
            >
              <X size={16} />
            </button>
          )}
        </>
      )}
    </div>
  );
}
