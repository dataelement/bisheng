import { SearchIcon } from 'lucide-react';
import * as React from 'react';

import { cn } from '~/utils';

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(({ className, ...props }, ref) => {
  return (
    <input
      className={cn(
        'flex h-10 w-full rounded-lg border border-input bg-transparent px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
        className ?? '',
      )}
      ref={ref}
      {...props}
    />
  );
});

Input.displayName = 'Input';

const SearchInput = React.forwardRef<HTMLInputElement, InputProps & { inputClassName?: string, iconClassName?: string }>(
  ({ className, inputClassName, iconClassName, ...props }, ref) => {
    return <div className={cn("relative", className)}>
      <SearchIcon className={cn("h-5 w-5 absolute left-2 top-2 text-gray-950 dark:text-gray-500 z-10", iconClassName)} />
      <Input type="text" ref={ref} className={cn("pl-8 bg-search-input", inputClassName)} {...props}></Input>
    </div>
  }
)

SearchInput.displayName = "SearchInput"

export { Input, SearchInput };
