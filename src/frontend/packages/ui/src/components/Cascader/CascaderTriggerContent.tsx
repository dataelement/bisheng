import * as React from 'react';
import cn from '../../utils/cn';
import type { InputSize } from '../Input/shared';
import { SelectTags } from '../Select/SelectTags';
import type { SelectOption } from '../Select/types';
import { SELECTION_CHEVRON_SIZE, type SelectionVariant } from '../shared/SelectionTrigger';
import { Tooltip } from '../Tooltip/Tooltip';
import type { CascaderPath } from './types';
import { shortestLabels, type CascaderEntry } from './utils';

interface TruncatedValueProps {
  value: string;
  placeholder?: string;
}

function TruncatedValue({ value, placeholder }: TruncatedValueProps) {
  const ref = React.useRef<HTMLSpanElement>(null);
  const [clipped, setClipped] = React.useState(false);
  const node = (
    <span
      ref={ref}
      className={cn('min-w-0 flex-1 truncate', !value && 'text-text-3')}
      onPointerEnter={() => {
        const element = ref.current;
        if (element) setClipped(element.scrollWidth > element.clientWidth);
      }}
    >
      {value || placeholder}
    </span>
  );
  if (!value) return node;
  return (
    <Tooltip content={value} disabled={!clipped}>
      {node}
    </Tooltip>
  );
}

export interface CascaderTriggerContentProps {
  variant: SelectionVariant;
  size: InputSize;
  multiple: boolean;
  hasValue: boolean;
  disabled: boolean;
  placeholder?: string;
  separator: string;
  removeLabel: string;
  selectedEntries: CascaderEntry[];
  singleLabel: string;
  searchableInTrigger: boolean;
  searchInput: React.ReactNode;
  open: boolean;
  onRemove: (path: CascaderPath) => void;
}

export function CascaderTriggerContent({
  variant,
  size,
  multiple,
  hasValue,
  disabled,
  placeholder,
  separator,
  removeLabel,
  selectedEntries,
  singleLabel,
  searchableInTrigger,
  searchInput,
  open,
  onRemove,
}: CascaderTriggerContentProps) {
  if (variant === 'icon') {
    const lastOptions = selectedEntries[0]?.options ?? [];
    const icon = lastOptions[lastOptions.length - 1]?.icon;
    return icon !== undefined ? (
      <span
        className="flex shrink-0"
        style={{ width: SELECTION_CHEVRON_SIZE[size], height: SELECTION_CHEVRON_SIZE[size] }}
      >
        {icon}
      </span>
    ) : null;
  }

  if (multiple && hasValue) {
    const labels = shortestLabels(selectedEntries, separator);
    const paths = new Map(selectedEntries.map((entry) => [entry.key, entry.path]));
    const options: SelectOption[] = selectedEntries.map((entry) => ({
      value: entry.key,
      label:
        labels.get(entry.key) ??
        entry.options[entry.options.length - 1]?.label ??
        String(entry.path[entry.path.length - 1] ?? ''),
    }));
    return (
      <SelectTags
        options={options}
        disabled={disabled}
        removeLabel={removeLabel}
        onRemove={(option) => {
          const path = paths.get(String(option.value));
          if (path) onRemove(path);
        }}
        search={searchInput}
      />
    );
  }

  if (searchableInTrigger) {
    return (
      <span className="grid min-w-0 flex-1 items-center">
        {searchInput}
        {!open && singleLabel && (
          <span className="pointer-events-none truncate [grid-area:1/1]">{singleLabel}</span>
        )}
      </span>
    );
  }

  return <TruncatedValue value={singleLabel} placeholder={placeholder} />;
}
