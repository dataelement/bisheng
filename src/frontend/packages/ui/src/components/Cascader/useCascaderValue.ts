import * as React from 'react';
import type { CascaderPath, CascaderProps } from './types';
import type { CascaderEntry } from './utils';

function initialValue(props: CascaderProps): CascaderPath[] {
  if (props.multiple === true) return props.defaultValue ?? [];
  return props.defaultValue ? [props.defaultValue] : [];
}

export function useCascaderValue(
  props: CascaderProps,
  resolveEntry: (path: CascaderPath) => CascaderEntry,
): { selected: CascaderPath[]; commit: (next: CascaderPath[]) => void } {
  const [innerValue, setInnerValue] = React.useState<CascaderPath[]>(() => initialValue(props));
  const controlled = props.value !== undefined;
  const selected = React.useMemo(
    () =>
      controlled
        ? props.multiple === true
          ? props.value ?? []
          : props.value
            ? [props.value]
            : []
        : innerValue,
    [controlled, innerValue, props.multiple, props.value],
  );
  const commit = React.useCallback(
    (next: CascaderPath[]) => {
      if (!controlled) setInnerValue(next);
      if (props.multiple === true) {
        props.onChange?.(next, next.map((path) => resolveEntry(path).options));
      } else {
        const path = next[0] ?? null;
        props.onChange?.(path, path ? resolveEntry(path).options : []);
      }
    },
    [controlled, props, resolveEntry],
  );
  return { selected, commit };
}
