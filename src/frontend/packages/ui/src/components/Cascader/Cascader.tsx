import * as React from 'react';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import cn from '../../utils/cn';
import { useMediaQuery, PHONE_QUERY } from '../../utils/useMediaQuery';
import { FIELD_BASE } from '../Input/shared';
import { useDebounced } from '../Select/useSelectList';
import {
  DEFAULT_PANEL_RADIUS,
  PANEL_COLLISION_PADDING,
  PANEL_SIDE_OFFSET,
  panelSurfaceClass,
} from '../shared/menuSurface';
import { SelectionTrigger } from '../shared/SelectionTrigger';
import { Tooltip } from '../Tooltip/Tooltip';
import { CascaderMobilePanel } from './CascaderMobilePanel';
import { CascaderPanel, cascaderOptionId, type CascaderColumn } from './CascaderPanel';
import { CascaderTriggerContent } from './CascaderTriggerContent';
import type { CascaderOption, CascaderPath, CascaderProps } from './types';
import {
  activePositionForPath,
  cascaderPathKey,
  descendantLeaves,
  filterEntries,
  flattenCascader,
  resolveOptionPath,
  type CascaderEntry,
} from './utils';
import { useCascaderValue } from './useCascaderValue';

export function Cascader(props: CascaderProps) {
  const {
    options,
    size = 'medium',
    status = 'default',
    variant = 'outlined',
    radius,
    panelRadius = DEFAULT_PANEL_RADIUS,
    placeholder,
    disabled = false,
    readOnly = false,
    checkStrictly = false,
    expandTrigger = 'click',
    showSearch,
    onSearch,
    filterOption,
    loadData,
    onLoadError,
    allowClear = false,
    onClear,
    loading = false,
    open: openProp,
    defaultOpen = false,
    onOpenChange,
    trigger,
    className,
    panelClassName,
    id,
    separator = ' / ',
    displayRender,
    emptyText = 'No data',
    noMatchText = 'No matches',
    loadingText = 'Loading…',
    loadErrorText = 'Load failed. Try again.',
    backLabel = 'Back',
    doneLabel = 'Done',
    clearLabel = 'Clear',
    removeLabel = 'Remove',
    searchPlaceholder = 'Search',
  } = props;
  const multiple = props.multiple === true;
  const phone = useMediaQuery(PHONE_QUERY);
  const interactive = !disabled && !readOnly;
  const generatedId = React.useId();
  const treeId = `${id ?? generatedId}-tree`;
  const anchorRef = React.useRef<HTMLElement | null>(null);
  const inputRef = React.useRef<HTMLInputElement | null>(null);
  const hoverTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const [loadedChildren, setLoadedChildren] = React.useState(
    () => new Map<string, CascaderOption[]>(),
  );
  const [loadingKeys, setLoadingKeys] = React.useState(() => new Set<string>());
  const [failedKeys, setFailedKeys] = React.useState(() => new Set<string>());
  const getChildren = React.useCallback(
    (option: CascaderOption, path: CascaderPath) =>
      loadedChildren.get(cascaderPathKey(path)) ?? option.children,
    [loadedChildren],
  );

  const allEntries = React.useMemo(
    () => flattenCascader(options, getChildren, true),
    [options, getChildren],
  );
  const knownEntries = React.useRef(new Map<string, CascaderEntry>());
  for (const entry of allEntries) knownEntries.current.set(entry.key, entry);
  const resolveEntry = React.useCallback(
    (path: CascaderPath): CascaderEntry =>
      knownEntries.current.get(cascaderPathKey(path)) ?? {
        key: cascaderPathKey(path),
        path,
        options: resolveOptionPath(options, path, getChildren),
      },
    [options, getChildren],
  );

  const { selected, commit } = useCascaderValue(props, resolveEntry);
  const selectedKeys = React.useMemo(() => new Set(selected.map(cascaderPathKey)), [selected]);

  const [innerOpen, setInnerOpen] = React.useState(defaultOpen);
  const isOpen = (openProp ?? innerOpen) && interactive;
  const openRef = React.useRef(isOpen);
  openRef.current = isOpen;
  const [keyword, setKeyword] = React.useState('');
  const search = useDebounced(onSearch);
  const selectableEntries = React.useMemo(
    () => flattenCascader(options, getChildren, checkStrictly),
    [options, getChildren, checkStrictly],
  );
  const searchable = trigger === undefined && (showSearch ?? selectableEntries.length > 10);
  const filter = filterOption ?? (onSearch === undefined);
  const searchResults = keyword
    ? filterEntries(selectableEntries, keyword, filter)
    : null;

  const [expandedPath, setExpandedPath] = React.useState<CascaderPath>([]);
  const [active, setActive] = React.useState({ level: 0, index: 0 });
  const columns = React.useMemo(() => {
    const result: CascaderColumn[] = [{ parentPath: [], parentOptions: [], options }];
    let items = options;
    const parentOptions: CascaderOption[] = [];
    for (let level = 0; level < expandedPath.length; level += 1) {
      const option = items.find((item) => item.value === expandedPath[level]);
      if (!option) break;
      parentOptions.push(option);
      const path = expandedPath.slice(0, level + 1);
      const children = getChildren(option, path);
      if (!children?.length) break;
      result.push({ parentPath: path, parentOptions: [...parentOptions], options: children });
      items = children;
    }
    return result;
  }, [expandedPath, getChildren, options]);

  const setOpen = React.useCallback(
    (next: boolean) => {
      if (next === openRef.current) return;
      openRef.current = next;
      if (openProp === undefined) setInnerOpen(next);
      onOpenChange?.(next);
      if (next) {
        const restoredPath = selected[0] ?? [];
        setExpandedPath(restoredPath);
        setActive(activePositionForPath(options, restoredPath, getChildren));
      } else if (keyword) {
        setKeyword('');
        search('');
      }
    },
    [getChildren, keyword, onOpenChange, openProp, options, search, selected],
  );

  React.useEffect(
    () => () => {
      if (hoverTimer.current) clearTimeout(hoverTimer.current);
    },
    [],
  );

  React.useEffect(() => {
    if (variant !== 'outlined' && status !== 'default') {
      console.warn(
        `[@bisheng/ui] Cascader variant="${variant}" shows no validation status; use variant="outlined" for a field that needs one.`,
      );
    }
  }, [status, variant]);

  const isParent = React.useCallback(
    (entry: CascaderEntry) => {
      const option = entry.options[entry.options.length - 1];
      if (!option) return false;
      const children = getChildren(option, entry.path);
      if (loadedChildren.has(entry.key)) return (children?.length ?? 0) > 0;
      return option.isLeaf === false || (children?.length ?? 0) > 0;
    },
    [getChildren, loadedChildren],
  );

  const subtreeLoaded = React.useCallback(
    function loaded(entry: CascaderEntry): boolean {
      const option = entry.options[entry.options.length - 1];
      if (!option) return false;
      const children = getChildren(option, entry.path);
      if (option.isLeaf === false && children === undefined) return false;
      return (children ?? []).every((child) => {
        const childPath = [...entry.path, child.value];
        return loaded({
          key: cascaderPathKey(childPath),
          path: childPath,
          options: [...entry.options, child],
        });
      });
    },
    [getChildren],
  );

  const canSelect = React.useCallback(
    (entry: CascaderEntry) => {
      const option = entry.options[entry.options.length - 1];
      if (!option || option.disabled) return false;
      if (checkStrictly || !isParent(entry)) return true;
      return multiple && subtreeLoaded(entry);
    },
    [checkStrictly, isParent, multiple, subtreeLoaded],
  );

  const getSelectionState = React.useCallback(
    (entry: CascaderEntry): boolean | 'indeterminate' => {
      if (checkStrictly || !multiple || !isParent(entry)) return selectedKeys.has(entry.key);
      const option = entry.options[entry.options.length - 1];
      if (!option) return false;
      const leaves = descendantLeaves(option, entry.path, getChildren).filter(
        (leaf) => !leaf.options.some((item) => item.disabled),
      );
      const count = leaves.filter((leaf) => selectedKeys.has(leaf.key)).length;
      if (count === 0) return false;
      return count === leaves.length ? true : 'indeterminate';
    },
    [checkStrictly, getChildren, isParent, multiple, selectedKeys],
  );

  const handleSelect = React.useCallback(
    (entry: CascaderEntry) => {
      if (!canSelect(entry)) return;
      if (!multiple) {
        commit([entry.path]);
        setOpen(false);
        return;
      }
      let targets = [entry];
      if (!checkStrictly && isParent(entry)) {
        const option = entry.options[entry.options.length - 1];
        if (!option) return;
        targets = descendantLeaves(option, entry.path, getChildren).filter(
          (leaf) => !leaf.options.some((item) => item.disabled),
        );
      }
      const targetKeys = new Set(targets.map((target) => target.key));
      const allSelected = targets.length > 0 && targets.every((target) => selectedKeys.has(target.key));
      const next = allSelected
        ? selected.filter((path) => !targetKeys.has(cascaderPathKey(path)))
        : [
            ...selected,
            ...targets.filter((target) => !selectedKeys.has(target.key)).map((target) => target.path),
          ];
      commit(next);
    },
    [canSelect, checkStrictly, commit, getChildren, isParent, multiple, selected, selectedKeys, setOpen],
  );

  const handleOpen = React.useCallback(
    async (entry: CascaderEntry) => {
      const option = entry.options[entry.options.length - 1];
      if (!option || option.disabled || !isParent(entry)) return;
      const children = getChildren(option, entry.path);
      if (children !== undefined) {
        if (children.length) {
          setExpandedPath(entry.path);
          setActive({ level: entry.path.length, index: 0 });
        }
        return;
      }
      if (!loadData || loadingKeys.has(entry.key)) return;
      setLoadingKeys((current) => new Set(current).add(entry.key));
      setFailedKeys((current) => {
        const next = new Set(current);
        next.delete(entry.key);
        return next;
      });
      try {
        const loaded = await loadData(option, entry.options);
        setLoadedChildren((current) => new Map(current).set(entry.key, loaded));
        if (loaded.length) {
          setExpandedPath(entry.path);
          setActive({ level: entry.path.length, index: 0 });
        } else if (!multiple && !checkStrictly) {
          commit([entry.path]);
          setOpen(false);
        }
      } catch (error) {
        setFailedKeys((current) => new Set(current).add(entry.key));
        onLoadError?.(error, option, entry.options);
      } finally {
        setLoadingKeys((current) => {
          const next = new Set(current);
          next.delete(entry.key);
          return next;
        });
      }
    },
    [checkStrictly, commit, getChildren, isParent, loadData, loadingKeys, multiple, onLoadError, setOpen],
  );

  const handleHoverOpen = (entry: CascaderEntry) => {
    if (phone || expandTrigger !== 'hover') return;
    if (hoverTimer.current) clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(() => void handleOpen(entry), 100);
  };

  const visibleEntries = React.useMemo(() => {
    if (searchResults !== null) return searchResults;
    const column = columns[active.level];
    if (!column) return [];
    return column.options.map((option) => {
      const path = [...column.parentPath, option.value];
      return {
        key: cascaderPathKey(path),
        path,
        options: [...column.parentOptions, option],
      };
    });
  }, [active.level, columns, searchResults]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (!interactive) return;
    const typing = event.currentTarget instanceof HTMLInputElement;
    if (!isOpen) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(event.key)) {
        if (event.key === ' ' && typing) return;
        event.preventDefault();
        setOpen(true);
      }
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
      return;
    }
    if (event.key === 'Tab') {
      setOpen(false);
      return;
    }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      let index = active.index;
      for (let step = 0; step < visibleEntries.length; step += 1) {
        index = (index + direction + visibleEntries.length) % visibleEntries.length;
        const candidate = visibleEntries[index];
        if (!candidate?.options[candidate.options.length - 1]?.disabled) break;
      }
      setActive({ level: searchResults ? 0 : active.level, index });
      return;
    }
    const entry = visibleEntries[active.index];
    if (!entry) return;
    if (event.key === 'ArrowRight' || event.key === 'Enter') {
      event.preventDefault();
      if (isParent(entry) && searchResults === null) void handleOpen(entry);
      else handleSelect(entry);
      return;
    }
    if (event.key === 'ArrowLeft' && searchResults === null && active.level > 0) {
      event.preventDefault();
      const previousLevel = active.level - 1;
      const parentValue = expandedPath[previousLevel];
      const index = columns[previousLevel]?.options.findIndex((item) => item.value === parentValue) ?? 0;
      setExpandedPath((path) => path.slice(0, previousLevel));
      setActive({ level: previousLevel, index: Math.max(index, 0) });
      return;
    }
    if (event.key === ' ' && !typing) {
      event.preventDefault();
      handleSelect(entry);
    }
  };

  const handleKeyword = (next: string) => {
    setKeyword(next);
    setActive({ level: 0, index: 0 });
    search(next);
    if (!isOpen) setOpen(true);
  };

  const handleClear = () => {
    commit([]);
    onClear?.();
  };

  const handleTriggerClick = (event: React.MouseEvent<HTMLElement>) => {
    if (!interactive) return;
    if (!phone && isOpen && searchable && event.target === inputRef.current) return;
    setOpen(!isOpen);
    if (!phone) inputRef.current?.focus();
  };

  const selectedEntries = selected.map(resolveEntry);
  const singleEntry = multiple ? undefined : selectedEntries[0];
  const singleLabels = singleEntry?.options.map((option) => option.label) ?? [];
  const singleLabel = singleEntry
    ? displayRender?.(singleLabels, singleEntry.options) ?? singleLabels.join(separator)
    : '';
  const hasValue = selected.length > 0;
  const searchableInTrigger = searchable && !phone;
  const comboboxProps: React.HTMLAttributes<HTMLElement> = {
    role: 'combobox',
    'aria-expanded': isOpen,
    'aria-haspopup': 'tree',
    'aria-controls': isOpen ? treeId : undefined,
    'aria-activedescendant': isOpen
      ? cascaderOptionId(treeId, searchResults ? 0 : active.level, active.index)
      : undefined,
    'aria-disabled': disabled || undefined,
    'aria-readonly': readOnly || undefined,
    'aria-invalid': (variant === 'outlined' && status === 'error') || undefined,
    'aria-label': props['aria-label'],
    'aria-labelledby': props['aria-labelledby'],
    onKeyDown: handleKeyDown,
  };

  const searchInput = searchableInTrigger ? (
    <input
      ref={inputRef}
      id={id}
      {...comboboxProps}
      aria-autocomplete="list"
      autoComplete="off"
      disabled={disabled}
      readOnly={readOnly}
      value={keyword}
      placeholder={
        multiple ? (hasValue ? undefined : placeholder) : isOpen ? singleLabel || placeholder : undefined
      }
      onChange={(event) => handleKeyword(event.target.value)}
      className={cn(FIELD_BASE, 'cursor-[inherit] [grid-area:1/1]', multiple && 'min-w-6')}
    />
  ) : null;

  const body = (
    <CascaderTriggerContent
      variant={variant}
      size={size}
      multiple={multiple}
      hasValue={hasValue}
      disabled={disabled}
      placeholder={placeholder}
      separator={separator}
      removeLabel={removeLabel}
      selectedEntries={selectedEntries}
      singleLabel={singleLabel}
      searchableInTrigger={searchableInTrigger}
      searchInput={searchInput}
      open={isOpen}
      onRemove={(path) => commit(selected.filter((item) => cascaderPathKey(item) !== cascaderPathKey(path)))}
    />
  );

  const ownCombobox = searchableInTrigger ? {} : { ...comboboxProps, id, tabIndex: disabled ? -1 : 0 };
  const triggerNode = (
    <SelectionTrigger
      ref={anchorRef}
      size={size}
      status={status}
      variant={variant}
      radius={radius}
      disabled={disabled}
      readOnly={readOnly}
      open={isOpen}
      interactive={interactive}
      hasValue={hasValue}
      allowClear={allowClear}
      clearLabel={clearLabel}
      body={body}
      hasMultipleTags={multiple && hasValue}
      customTrigger={trigger}
      className={className}
      comboboxProps={ownCombobox}
      onTriggerClick={handleTriggerClick}
      onClear={handleClear}
    />
  );
  let anchored = <PopoverPrimitive.Anchor asChild>{triggerNode}</PopoverPrimitive.Anchor>;
  if (variant === 'icon' && singleLabel) {
    anchored = (
      <Tooltip content={singleLabel} disabled={isOpen}>
        {anchored}
      </Tooltip>
    );
  }

  const panel = (
    <CascaderPanel
      treeId={treeId}
      columns={columns}
      searchResults={searchResults}
      activeLevel={searchResults ? 0 : active.level}
      activeIndex={active.index}
      expandedPath={expandedPath}
      multiple={multiple}
      checkStrictly={checkStrictly}
      panelRadius={panelRadius}
      loading={loading}
      loadingKeys={loadingKeys}
      failedKeys={failedKeys}
      emptyText={emptyText}
      noMatchText={noMatchText}
      loadingText={loadingText}
      loadErrorText={loadErrorText}
      separator={separator}
      phone={phone}
      onActive={(level, index) => setActive({ level, index })}
      onOpen={(entry) => void handleOpen(entry)}
      onHoverOpen={handleHoverOpen}
      onSelect={handleSelect}
      getSelectionState={getSelectionState}
      canSelect={canSelect}
      getChildren={getChildren}
    />
  );

  const mobilePanel = phone ? (
    <CascaderMobilePanel
      open={isOpen}
      treeId={treeId}
      multiple={multiple}
      searchable={searchable}
      keyword={keyword}
      columns={columns}
      searchResults={searchResults}
      panelRadius={panelRadius}
      panelClassName={panelClassName}
      backLabel={backLabel}
      doneLabel={doneLabel}
      clearLabel={clearLabel}
      searchPlaceholder={searchPlaceholder}
      panel={panel}
      onBack={() => {
        const nextLevel = Math.max(columns.length - 2, 0);
        setExpandedPath((path) => path.slice(0, nextLevel));
        setActive({ level: nextLevel, index: 0 });
      }}
      onKeyword={handleKeyword}
      onKeyDown={handleKeyDown}
      onClose={() => setOpen(false)}
    />
  ) : null;

  return (
    <PopoverPrimitive.Root
      open={isOpen}
      onOpenChange={(next) => {
        if (!next) setOpen(false);
      }}
    >
      {anchored}
      {!phone && (
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            id={treeId}
            role="tree"
            aria-multiselectable={multiple || undefined}
            side="bottom"
            align="start"
            sideOffset={PANEL_SIDE_OFFSET}
            collisionPadding={PANEL_COLLISION_PADDING}
            onOpenAutoFocus={(event) => event.preventDefault()}
            onCloseAutoFocus={(event) => event.preventDefault()}
            onInteractOutside={(event) => {
              if (anchorRef.current?.contains(event.target as Node)) event.preventDefault();
            }}
            className={panelSurfaceClass(
              panelRadius,
              cn(
                'flex w-max min-w-[var(--radix-popover-trigger-width)] max-w-[calc(100vw-16px)] overflow-x-auto',
                panelClassName,
              ),
            )}
          >
            {panel}
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      )}
      {mobilePanel}
    </PopoverPrimitive.Root>
  );
}
