import * as React from 'react';
import type { SelectOption, SelectProps, SelectValue } from './types';

/** One line of the listbox: a group title or an option. */
export type ListRow =
  | { kind: 'group'; key: string; label: string }
  | { kind: 'option'; key: string; option: SelectOption; index: number };

function defaultMatch(keyword: string, option: SelectOption): boolean {
  return option.label.toLowerCase().includes(keyword.toLowerCase());
}

/**
 * §5.3 / §6.3 — the visible rows for the current keyword: filtered, then
 * grouped in the order each group first appears. `options` is the flat list of
 * what is visible; a row's `index` points into it (the highlight works on it).
 */
export function useListRows(
  options: SelectOption[],
  keyword: string,
  filterOption: SelectProps['filterOption'],
): { rows: ListRow[]; visible: SelectOption[] } {
  return React.useMemo(() => {
    const match =
      !keyword || filterOption === false
        ? null
        : typeof filterOption === 'function'
          ? filterOption
          : defaultMatch;
    const filtered = match ? options.filter((option) => match(keyword, option)) : options;

    // Ungrouped options stay where they are; grouped ones gather under their title.
    const order: (string | undefined)[] = [];
    const buckets = new Map<string | undefined, SelectOption[]>();
    for (const option of filtered) {
      if (!buckets.has(option.group)) {
        buckets.set(option.group, []);
        order.push(option.group);
      }
      buckets.get(option.group)?.push(option);
    }

    const rows: ListRow[] = [];
    const visible: SelectOption[] = [];
    for (const group of order) {
      if (group !== undefined) rows.push({ kind: 'group', key: `group:${group}`, label: group });
      for (const option of buckets.get(group) ?? []) {
        rows.push({ kind: 'option', key: `option:${option.value}`, option, index: visible.length });
        visible.push(option);
      }
    }
    return { rows, visible };
  }, [options, keyword, filterOption]);
}

/**
 * §8 keyboard model: one highlighted option, moved by the arrow keys and the
 * pointer alike (hover and highlight are the same look on purpose, §7.2),
 * skipping disabled options and stopping at either end.
 */
export function useHighlight(visible: SelectOption[]) {
  const [highlight, setHighlight] = React.useState(-1);

  // A shrinking list (typing a keyword) must not leave the highlight past the end.
  React.useEffect(() => {
    setHighlight((current) => (current >= visible.length ? -1 : current));
  }, [visible.length]);

  const move = React.useCallback(
    (delta: 1 | -1) => {
      setHighlight((current) => {
        let next = current;
        for (let step = 0; step < visible.length; step += 1) {
          next = next + delta;
          if (next < 0 || next >= visible.length) return current;
          if (!visible[next].disabled) return next;
        }
        return current;
      });
    },
    [visible],
  );

  /** Highlight the first enabled option at or after `from` (wrapping), or nothing. */
  const reset = React.useCallback(
    (from: number) => {
      const start = Math.max(0, from);
      for (let step = 0; step < visible.length; step += 1) {
        const index = (start + step) % visible.length;
        if (!visible[index].disabled) {
          setHighlight(index);
          return;
        }
      }
      setHighlight(-1);
    },
    [visible],
  );

  return { highlight, setHighlight, move, reset };
}

/**
 * §8 — without search, typing letters jumps to the first option whose label
 * starts with them; keys pressed within 500ms accumulate into one prefix.
 */
export function useTypeahead(visible: SelectOption[], onMatch: (index: number) => void) {
  const buffer = React.useRef('');
  const timer = React.useRef<number>();

  React.useEffect(() => () => window.clearTimeout(timer.current), []);

  return React.useCallback(
    (key: string) => {
      buffer.current += key.toLowerCase();
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => {
        buffer.current = '';
      }, 500);
      const index = visible.findIndex(
        (option) => !option.disabled && option.label.toLowerCase().startsWith(buffer.current),
      );
      if (index >= 0) onMatch(index);
    },
    [visible, onMatch],
  );
}

/** Controlled-or-not value, normalised to an array so single and multiple share one path. */
export function useSelectedValues(props: SelectProps): {
  selected: SelectValue[];
  commit: (next: SelectValue[], options: SelectOption[]) => void;
} {
  const isControlled = props.value !== undefined;
  const [inner, setInner] = React.useState<SelectValue[]>(() => toArray(props.defaultValue));
  const selected = isControlled ? toArray(props.value) : inner;

  const commit = (next: SelectValue[], all: SelectOption[]) => {
    if (!isControlled) setInner(next);
    const picked = next
      .map((value) => all.find((option) => option.value === value))
      .filter((option): option is SelectOption => option !== undefined);
    if (props.multiple) {
      props.onChange?.(next, picked);
    } else {
      props.onChange?.(next[0] ?? null, picked[0]);
    }
  };

  return { selected, commit };
}

function toArray(value: SelectValue | SelectValue[] | null | undefined): SelectValue[] {
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
}

/** §6.3 — server search fires 300ms after the last keystroke. */
export function useDebounced(callback: ((keyword: string) => void) | undefined, delay = 300) {
  const timer = React.useRef<number>();
  const latest = React.useRef(callback);
  latest.current = callback;

  React.useEffect(() => () => window.clearTimeout(timer.current), []);

  return React.useCallback(
    (keyword: string) => {
      window.clearTimeout(timer.current);
      if (!latest.current) return;
      timer.current = window.setTimeout(() => latest.current?.(keyword), delay);
    },
    [delay],
  );
}
