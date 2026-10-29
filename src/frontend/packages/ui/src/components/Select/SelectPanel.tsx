import * as React from 'react';
import { Outlined } from 'bisheng-icons';
import cn from '../../utils/cn';
import { Checkbox } from '../Checkbox/Checkbox';
import { Tooltip } from '../Tooltip/Tooltip';
import {
  GROUP_LABEL,
  MENU_STACK,
  OPTION_CHECK,
  OPTION_DESCRIPTION,
  OPTION_ICON,
  PANEL_MESSAGE,
  optionClass,
  type PanelRadius,
} from '../shared/menuSurface';
import type { SelectOption, SelectValue } from './types';
import type { ListRow } from './useSelectList';

/** Stable DOM id of an option, for `aria-activedescendant`. */
export function optionId(listboxId: string, index: number): string {
  return `${listboxId}-option-${index}`;
}

/** Distance from the bottom that counts as "reached the end" for load-more. */
const LOAD_MORE_THRESHOLD = 24;

/** §6.5 — true once the scrolling panel is (nearly) at its end. */
export function reachedEnd(node: HTMLElement): boolean {
  return node.scrollHeight - node.scrollTop - node.clientHeight <= LOAD_MORE_THRESHOLD;
}

interface OptionLabelProps {
  option: SelectOption;
}

/**
 * §5.2 — one line, ellipsis, and the full text on hover — but ONLY when it is
 * actually clipped, measured on pointer-enter so a list of short labels mounts
 * no tooltips. The tooltip goes to the right so it never covers the rows below.
 */
function OptionLabel({ option }: OptionLabelProps) {
  const [clipped, setClipped] = React.useState(false);
  return (
    <span className="flex min-w-0 flex-1 flex-col">
      <Tooltip content={option.label} side="right" disabled={!clipped}>
        <span
          className="truncate"
          onPointerEnter={(event) =>
            setClipped(event.currentTarget.scrollWidth > event.currentTarget.clientWidth)
          }
        >
          {option.label}
        </span>
      </Tooltip>
      {option.description !== undefined && (
        <span className={OPTION_DESCRIPTION}>{option.description}</span>
      )}
    </span>
  );
}

export interface SelectPanelProps {
  listboxId: string;
  rows: ListRow[];
  highlight: number;
  selected: SelectValue[];
  multiple: boolean;
  radius: PanelRadius;
  /** True while the trigger holds a search keyword — picks the empty message. */
  searching: boolean;
  loading: boolean;
  loadingMore: boolean;
  emptyText: React.ReactNode;
  noMatchText: React.ReactNode;
  loadingText: React.ReactNode;
  onHighlight: (index: number) => void;
  onPick: (option: SelectOption) => void;
  'aria-label'?: string;
  'aria-labelledby'?: string;
}

/**
 * The listbox inside the panel (§5.2–§6.5, §7.2). Focus never enters it: the
 * trigger keeps focus and points at the highlighted option through
 * `aria-activedescendant`, which is what lets the user keep typing a search
 * keyword while moving through the results.
 */
export const SelectPanel = React.forwardRef<HTMLDivElement, SelectPanelProps>(function SelectPanel(
  {
    listboxId,
    rows,
    highlight,
    selected,
    multiple,
    radius,
    searching,
    loading,
    loadingMore,
    emptyText,
    noMatchText,
    loadingText,
    onHighlight,
    onPick,
    ...aria
  },
  ref,
) {
  const listRef = React.useRef<HTMLDivElement | null>(null);

  // Keep the highlighted option in view — arrow keys past the 8th row, and the
  // §8 "open scrolled to the current value".
  React.useEffect(() => {
    if (highlight < 0) return;
    const node = listRef.current?.querySelector<HTMLElement>(`#${CSS.escape(optionId(listboxId, highlight))}`);
    node?.scrollIntoView({ block: 'nearest' });
  }, [highlight, listboxId]);

  // §6.5 — one line of text, never an illustration.
  if (loading) {
    return (
      <div className={PANEL_MESSAGE} role="status">
        <Outlined.Loading className="size-4 animate-spin" aria-hidden />
        {loadingText}
      </div>
    );
  }
  if (rows.length === 0) {
    return <div className={PANEL_MESSAGE}>{searching ? noMatchText : emptyText}</div>;
  }

  const selectedSet = new Set(selected);

  return (
    <div
      ref={(node) => {
        listRef.current = node;
        if (typeof ref === 'function') ref(node);
        else if (ref) ref.current = node;
      }}
      id={listboxId}
      role="listbox"
      aria-multiselectable={multiple || undefined}
      // The panel shell owns padding and scrolling; the row rhythm lives here.
      className={MENU_STACK}
      {...aria}
    >
      {rows.map((row) => {
        if (row.kind === 'group') {
          return (
            <div key={row.key} role="presentation" className={GROUP_LABEL}>
              {row.label}
            </div>
          );
        }
        const { option, index } = row;
        const isSelected = selectedSet.has(option.value);
        return (
          <div
            key={row.key}
            id={optionId(listboxId, index)}
            role="option"
            aria-selected={isSelected}
            aria-disabled={option.disabled || undefined}
            data-highlighted={index === highlight ? '' : undefined}
            data-disabled={option.disabled ? '' : undefined}
            className={optionClass(
              radius,
              // §7.2 — single: weight 500 + the check, NO fill (fill is hover's).
              !multiple && isSelected ? 'font-medium' : undefined,
            )}
            // Keep focus (and the caret of a search box) in the trigger.
            onMouseDown={(event) => event.preventDefault()}
            onPointerMove={() => {
              if (index !== highlight && !option.disabled) onHighlight(index);
            }}
            onClick={() => {
              if (!option.disabled) onPick(option);
            }}
          >
            {multiple && (
              // §7.2 — multiple: a real check box on the left, 8px from the text.
              // Decorative here: the row is the option and carries aria-selected.
              <Checkbox
                checked={isSelected}
                disabled={option.disabled}
                tabIndex={-1}
                aria-hidden
                className="pointer-events-none"
              />
            )}
            {option.icon !== undefined && <span className={OPTION_ICON}>{option.icon}</span>}
            <OptionLabel option={option} />
            {!multiple && isSelected && <Outlined.Check className={OPTION_CHECK} aria-hidden />}
          </div>
        );
      })}
      {loadingMore && (
        <div className={cn(PANEL_MESSAGE, 'py-1.5')} role="status">
          <Outlined.Loading className="size-4 animate-spin" aria-hidden />
          {loadingText}
        </div>
      )}
    </div>
  );
});
