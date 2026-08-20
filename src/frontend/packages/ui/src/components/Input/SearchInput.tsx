import * as React from 'react';
import { Outlined } from 'bisheng-icons';
import { Input, type InputProps } from './Input';

/**
 * SearchInput — the filter / search form of the base field (组件-Input输入框.md §2).
 *
 * Magnifier in the prefix so the box says what it is at a glance, Enter runs the
 * search, and clear is ON by default (§4.3: search and filter fields get it —
 * dropping a query costs the user one keystroke, not a paragraph).
 */
export interface SearchInputProps extends Omit<InputProps, 'type' | 'prefix'> {
  /** Runs on Enter with the current text. Filtering as you type stays on `onChange`. */
  onSearch?: (value: string) => void;
  /** Replace the magnifier — e.g. a link icon for a URL filter. */
  prefixIcon?: React.ReactNode;
}

export const SearchInput = React.forwardRef<HTMLInputElement, SearchInputProps>(
  function SearchInput({ onSearch, prefixIcon, allowClear = true, onKeyDown, ...props }, ref) {
    const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
      onKeyDown?.(event);
      // IME: Enter while composing commits the candidate, it does not search.
      if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
        onSearch?.(event.currentTarget.value);
      }
    };

    return (
      <Input
        ref={ref}
        type="search"
        prefix={prefixIcon ?? <Outlined.Search />}
        allowClear={allowClear}
        onKeyDown={handleKeyDown}
        {...props}
      />
    );
  },
);
