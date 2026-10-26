import * as React from 'react';
import * as PopoverPrimitive from '@radix-ui/react-popover';
import cn from '../../utils/cn';
import { FIELD_BASE } from '../Input/shared';
import {
  DEFAULT_PANEL_RADIUS,
  PANEL_COLLISION_PADDING,
  PANEL_SIDE_OFFSET,
  panelClass,
} from '../shared/menuSurface';
import { SELECTION_CHEVRON_SIZE, SelectionTrigger } from '../shared/SelectionTrigger';
import { Tooltip } from '../Tooltip/Tooltip';
import { SelectPanel, optionId, reachedEnd } from './SelectPanel';
import { SelectTags } from './SelectTags';
import type { SelectOption, SelectProps, SelectValue } from './types';
import {
  useDebounced,
  useHighlight,
  useListRows,
  useSelectedValues,
  useTypeahead,
} from './useSelectList';

/**
 * Select — pick one or several values from a given list, and show what was
 * picked in the box (组件-Select选择器.md v1).
 *
 * Trigger and panel are ONE component (§2). What it pins down and a page cannot
 * restate: the trigger shares the Input shell — the 24/32/40 ladder, the gray
 * focus chain, the seven states (§4, §7.1); the panel shell, 32px rows and
 * group / separator look shared with Dropdown (§5, `shared/menuSurface.ts`);
 * the right-side check for single and the left check box for multiple (§7.2);
 * search in the trigger itself past 10 options (§6.3); tags folding into "+N"
 * on a trigger that never grows taller (§6.2); and a panel that opens below,
 * flips above, and never covers the trigger (§8).
 *
 * Built on a Radix Popover + a listbox of our own rather than Radix Select:
 * Radix Select has neither multiple selection nor typing in the trigger, and
 * one code path keeps single, multiple and searchable looking and behaving
 * alike. Focus stays on the trigger; the highlighted option is announced via
 * `aria-activedescendant`.
 *
 * Not this component: actions with no "current value" (that is Dropdown), a
 * tree / cascade of options, or ≤5 options that fit on the page (Radio /
 * Segmented, §1).
 */

/** §5.1 — below this trigger width the panel sizes to its content instead. */
const NARROW_TRIGGER = 160;

export function Select(props: SelectProps) {
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
    showSearch,
    onSearch,
    filterOption,
    allowClear = false,
    onClear,
    loading = false,
    onLoadMore,
    loadingMore = false,
    open: openProp,
    defaultOpen = false,
    onOpenChange,
    trigger,
    className,
    panelClassName,
    id,
    emptyText = 'No data',
    noMatchText = 'No matches',
    loadingText = 'Loading…',
    clearLabel = 'Clear',
    removeLabel = 'Remove',
  } = props;
  const multiple = props.multiple === true;
  const outlined = variant === 'outlined';
  // §6.3 — search past 10 options; never on a custom arrow-entry trigger.
  const searchable = trigger === undefined && (showSearch ?? options.length > 10);
  // Server search filters on the server; local filtering would hide its results.
  const filter = filterOption ?? (onSearch === undefined);

  const generatedId = React.useId();
  const listboxId = `${id ?? generatedId}-listbox`;
  const anchorRef = React.useRef<HTMLElement | null>(null);
  const inputRef = React.useRef<HTMLInputElement | null>(null);

  // ---- open state ----------------------------------------------------------
  const [innerOpen, setInnerOpen] = React.useState(defaultOpen);
  const interactive = !disabled && !readOnly;
  const isOpen = (openProp ?? innerOpen) && interactive;
  const openRef = React.useRef(isOpen);
  openRef.current = isOpen;
  const [keyword, setKeyword] = React.useState('');
  const search = useDebounced(onSearch);

  const setOpen = (next: boolean) => {
    if (next === openRef.current) return;
    openRef.current = next;
    if (openProp === undefined) setInnerOpen(next);
    onOpenChange?.(next);
    if (!next && keyword) {
      setKeyword('');
      search('');
    }
  };

  // ---- value ---------------------------------------------------------------
  const { selected, commit } = useSelectedValues(props);
  // Remember every option ever passed in, so a picked value keeps its label
  // after a server search has narrowed `options` to something else.
  const known = React.useRef(new Map<SelectValue, SelectOption>());
  for (const option of options) known.current.set(option.value, option);
  const resolve = (value: SelectValue): SelectOption =>
    known.current.get(value) ?? { value, label: String(value) };
  const selectedOptions = selected.map(resolve);
  const allKnown = () => Array.from(known.current.values());

  // ---- list + highlight ----------------------------------------------------
  const { rows, visible } = useListRows(options, keyword, filter);
  const { highlight, setHighlight, move, reset } = useHighlight(visible);
  const typeahead = useTypeahead(visible, setHighlight);

  // §8 — open on the current value (scrolled into view by the panel), else the first option.
  React.useEffect(() => {
    if (!isOpen) {
      setHighlight(-1);
      return;
    }
    const current = visible.findIndex((option) => selected.includes(option.value));
    reset(current >= 0 ? current : 0);
    // Only on open: re-running on every value change would yank the highlight
    // back while the user is ticking boxes in a multiple select.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  // A new keyword re-starts the highlight at the first match.
  React.useEffect(() => {
    if (isOpen && keyword) reset(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [keyword]);

  // §5.1 — wide triggers get a panel of the same width; narrow ones (filter
  // bars, ghost / icon) let the panel size to its content, up to 320px.
  const [narrow, setNarrow] = React.useState(false);
  React.useLayoutEffect(() => {
    if (isOpen && anchorRef.current) setNarrow(anchorRef.current.offsetWidth < NARROW_TRIGGER);
  }, [isOpen]);

  // §3.1 — ghost / icon carry no validation; say so instead of silently dropping it.
  React.useEffect(() => {
    if (!outlined && status !== 'default') {
      console.warn(
        `[@bisheng/ui] Select variant="${variant}" shows no validation status (Select spec, section 3.1); use variant="outlined" for a field that needs one.`,
      );
    }
  }, [outlined, status, variant]);

  // ---- actions -------------------------------------------------------------
  const handlePick = (option: SelectOption) => {
    if (multiple) {
      // §3 — multiple stays open: users usually pick several in a row.
      const next = selected.includes(option.value)
        ? selected.filter((value) => value !== option.value)
        : [...selected, option.value];
      commit(next, allKnown());
      if (keyword) {
        setKeyword('');
        search('');
      }
    } else {
      // §3 — single closes as soon as a value is picked.
      commit([option.value], allKnown());
      setOpen(false);
    }
  };

  const handleRemove = (option: SelectOption) => {
    commit(
      selected.filter((value) => value !== option.value),
      allKnown(),
    );
  };

  const handleClear = () => {
    commit([], allKnown());
    onClear?.();
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLElement>) => {
    if (!interactive) return;
    switch (event.key) {
      case 'ArrowDown':
      case 'ArrowUp':
        event.preventDefault();
        if (!isOpen) setOpen(true);
        else move(event.key === 'ArrowDown' ? 1 : -1);
        return;
      case 'Enter':
        event.preventDefault();
        if (!isOpen) setOpen(true);
        else if (highlight >= 0 && visible[highlight]) handlePick(visible[highlight]);
        return;
      case ' ':
        // Space types a space into a search box; elsewhere it acts like Enter.
        if (searchable) return;
        event.preventDefault();
        if (!isOpen) setOpen(true);
        else if (highlight >= 0 && visible[highlight]) handlePick(visible[highlight]);
        return;
      case 'Escape':
        if (isOpen) {
          // Close the panel only — not a dialog this select sits in.
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
        }
        return;
      case 'Tab':
        // §8 — Tab closes the panel and moves on to the next control.
        setOpen(false);
        return;
      case 'Backspace':
        if (multiple && searchable && keyword === '' && selected.length > 0) {
          handleRemove(resolve(selected[selected.length - 1]));
        }
        return;
      default:
        // §8 — no search: a letter jumps to the first option starting with it.
        if (!searchable && event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
          if (!isOpen) setOpen(true);
          typeahead(event.key);
        }
    }
  };

  const handleTriggerClick = (event: React.MouseEvent<HTMLElement>) => {
    if (!interactive) return;
    // Clicking into the search box of an open panel is typing, not closing.
    if (isOpen && searchable && event.target === inputRef.current) return;
    setOpen(!isOpen);
    inputRef.current?.focus();
  };

  // ---- trigger -------------------------------------------------------------
  const activeId = isOpen && highlight >= 0 ? optionId(listboxId, highlight) : undefined;
  const comboboxProps = {
    role: 'combobox',
    'aria-expanded': isOpen,
    'aria-haspopup': 'listbox' as const,
    'aria-controls': isOpen ? listboxId : undefined,
    'aria-activedescendant': activeId,
    'aria-disabled': disabled || undefined,
    'aria-readonly': readOnly || undefined,
    'aria-invalid': (outlined && status === 'error') || undefined,
    'aria-label': props['aria-label'],
    'aria-labelledby': props['aria-labelledby'],
    onKeyDown: handleKeyDown,
  };

  const single = multiple ? undefined : selectedOptions[0];
  const hasValue = selected.length > 0;
  const chevronSize = SELECTION_CHEVRON_SIZE[size];

  const searchInput = searchable ? (
    <input
      ref={inputRef}
      id={id}
      {...comboboxProps}
      aria-autocomplete="list"
      autoComplete="off"
      disabled={disabled}
      readOnly={readOnly}
      value={keyword}
      // §6.3 — once open, the current value turns into the faint hint and
      // disappears with the first keystroke.
      placeholder={
        multiple
          ? hasValue
            ? undefined
            : placeholder
          : isOpen
            ? (single?.label ?? placeholder)
            : hasValue
              ? undefined
              : placeholder
      }
      onChange={(event) => {
        setKeyword(event.target.value);
        search(event.target.value);
        if (!isOpen) setOpen(true);
      }}
      className={cn(FIELD_BASE, 'cursor-[inherit] [grid-area:1/1]', multiple && 'min-w-6')}
    />
  ) : null;

  let body: React.ReactNode;
  if (variant === 'icon') {
    body = single?.icon !== undefined && (
      <span className="flex shrink-0" style={{ width: chevronSize, height: chevronSize }}>
        {single.icon}
      </span>
    );
  } else if (multiple && (hasValue || searchable)) {
    // Keep the search input mounted when the first tag is added or the last removed.
    // Replacing it lets a parent dialog reclaim focus and dismiss the panel.
    body = (
      <SelectTags
        options={selectedOptions}
        disabled={disabled}
        removeLabel={removeLabel}
        onRemove={handleRemove}
        search={searchInput}
      />
    );
  } else if (searchable) {
    body = (
      <span className="grid min-w-0 flex-1 items-center">
        {searchInput}
        {!isOpen && single && (
          <span className="pointer-events-none truncate [grid-area:1/1]">{single.label}</span>
        )}
      </span>
    );
  } else {
    body = (
      <span className={cn('min-w-0 truncate', outlined && 'flex-1', !single && 'text-text-3')}>
        {single?.label ?? placeholder}
      </span>
    );
  }

  // The trigger itself is the combobox unless a search input inside it is.
  const ownCombobox = searchable ? {} : { ...comboboxProps, id, tabIndex: disabled ? -1 : 0 };
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
  if (variant === 'icon' && single) {
    anchored = (
      <Tooltip content={single.label} disabled={isOpen}>
        {anchored}
      </Tooltip>
    );
  }

  return (
    <PopoverPrimitive.Root
      open={isOpen}
      onOpenChange={(next) => {
        if (!next) setOpen(false);
      }}
    >
      {anchored}
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="bottom"
          align="start"
          sideOffset={PANEL_SIDE_OFFSET}
          collisionPadding={PANEL_COLLISION_PADDING}
          // Focus stays on the trigger the whole time (aria-activedescendant).
          onOpenAutoFocus={(event) => event.preventDefault()}
          onCloseAutoFocus={(event) => event.preventDefault()}
          // A press on the trigger is the trigger's own toggle, not "outside".
          onInteractOutside={(event) => {
            if (anchorRef.current?.contains(event.target as Node)) event.preventDefault();
          }}
          onScroll={(event) => {
            if (onLoadMore && !loadingMore && reachedEnd(event.currentTarget)) onLoadMore();
          }}
          className={panelClass(
            panelRadius,
            cn(
              narrow
                ? 'w-max min-w-[var(--radix-popover-trigger-width)] max-w-[320px]'
                : 'w-[var(--radix-popover-trigger-width)]',
              panelClassName,
            ),
          )}
        >
          <SelectPanel
            listboxId={listboxId}
            rows={rows}
            highlight={highlight}
            selected={selected}
            multiple={multiple}
            radius={panelRadius}
            searching={keyword !== ''}
            loading={loading}
            loadingMore={loadingMore}
            emptyText={emptyText}
            noMatchText={noMatchText}
            loadingText={loadingText}
            onHighlight={setHighlight}
            onPick={handlePick}
            aria-label={props['aria-label']}
            aria-labelledby={props['aria-labelledby']}
          />
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
