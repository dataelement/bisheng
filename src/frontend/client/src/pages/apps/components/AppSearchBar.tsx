import { Search, X } from 'lucide-react';
import { useRef, useState } from 'react';
import { cn } from '~/utils';

interface AppSearchBarProps {
  value: string;
  onChange: (value: string) => void;
}

/**
 * Expandable search bar for the app center.
 * Collapses to an icon when empty, expands to full input on click.
 */
export function AppSearchBar({ value, onChange }: AppSearchBarProps) {
  const [isOpen, setIsOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const expanded = isOpen || !!value;

  return (
    <div
      className={cn(
        'flex items-center bg-gray-50 border border-gray-100 rounded-lg px-3 py-1.5 transition-all',
        expanded ? 'w-64' : 'w-10 h-10 justify-center cursor-pointer',
      )}
      onClick={() => {
        if (!expanded) {
          setIsOpen(true);
          // Focus after the transition
          setTimeout(() => inputRef.current?.focus(), 50);
        }
      }}
    >
      <Search size={18} className="text-gray-400 flex-shrink-0" />
      {expanded && (
        <>
          <input
            ref={inputRef}
            autoFocus
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="ml-2 w-full bg-transparent outline-none text-sm"
            placeholder="搜索应用..."
            onBlur={() => {
              if (!value) setIsOpen(false);
            }}
          />
          {value && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onChange('');
                inputRef.current?.focus();
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
