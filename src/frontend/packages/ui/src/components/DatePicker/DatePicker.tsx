import * as Popover from '@radix-ui/react-popover';
import { Filled, Outlined } from 'bisheng-icons';
import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent, type PointerEvent, type ReactElement } from 'react';
import cn from '../../utils/cn';
import { PHONE_QUERY, useMediaQuery } from '../../utils/useMediaQuery';
import { Button } from '../Button/Button';
import { Input } from '../Input/Input';
import {
  CLEAR_VISIBILITY, CONTROL_ROW, FIELD_ACTION, FIELD_BASE, focusFieldFromShell, resolveState, shellStyles,
} from '../Input/shared';
import { DEFAULT_PANEL_RADIUS, PANEL_COLLISION_PADDING, PANEL_SIDE_OFFSET, panelSurfaceClass } from '../shared/menuSurface';
import { DatePickerCalendar } from './DatePickerCalendar';
import {
  currentDate, initialCalendar, isDayUnavailable, isRangeUnavailable, orderedRange, parseDateKey, parseInput,
  type UnboundedBoundary,
} from './dates';
import type { DatePickerOpenRange, DatePickerProps } from './types';

const DATE_FORMAT = 'YYYY-MM-DD';
const ACTION_CLASS =
  'self-stretch focus-visible:rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-current coarse-pointer:w-11';

type CalendarSession = ReturnType<typeof initialCalendar> & { today: Date; touch: boolean };
type FieldDraft = readonly [start: string, end: string];

// Keep ordinary range callbacks inferred as finite dates when the new mode is omitted.
export function DatePicker(props: Exclude<DatePickerProps, { allowOpenRange: true }>): ReactElement;
export function DatePicker(props: DatePickerProps): ReactElement;
export function DatePicker(props: DatePickerProps): ReactElement {
  const {
    locale, size = 'medium', status = 'default', disabled, readOnly, allowClear, className,
    value, onValidationChange,
  } = props;
  const isRange = props.mode === 'range';
  const isDateTime = props.mode === 'datetime';
  const openRange = isRange && props.allowOpenRange;
  const canLeaveOpen = openRange && props.maxRangeDays === undefined;
  const unlimitedLabel = openRange ? props.locale.unlimited : undefined;
  const state = resolveState(disabled, readOnly);
  const editable = state === 'editable';
  const committedStart = typeof value === 'string' ? value : value?.[0] ?? '';
  const committedEnd = typeof value === 'string' ? '' : value?.[1] ?? '';
  const timeZone = isDateTime ? props.timeZone : undefined;
  const format = isDateTime ? `${DATE_FORMAT} HH:mm${props.showSeconds ? ':ss' : ''}` : DATE_FORMAT;

  const fieldId = useId();
  const groupRef = useRef<HTMLDivElement>(null);
  const startRef = useRef<HTMLInputElement>(null);
  const endRef = useRef<HTMLInputElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const touchFieldRef = useRef<HTMLInputElement | null>(null);
  const wasTouchPointer = useRef(false);
  const focusGridOnOpen = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef(false);
  const phone = useMediaQuery(PHONE_QUERY);
  const compactTouch = useMediaQuery('(min-width: 576px) and (max-width: 669px) and (pointer: coarse)');

  const [draft, setDraft] = useState<FieldDraft | null>(null);
  const [showError, setShowError] = useState(false);
  const [session, setSession] = useState<CalendarSession>();
  const [open, setOpen] = useState(false);
  const [pendingStart, setPendingStart] = useState<string>();
  const [activeBoundary, setActiveBoundary] = useState<'start' | 'end'>('start');
  const [hoveredDay, setHoveredDay] = useState<string>();
  const [panelDay, setPanelDay] = useState('');
  const [timeParts, setTimeParts] = useState<string[]>([]);

  const [startText, endText] = draft ?? [committedStart, committedEnd];
  const parsedDraft = editable && draft ? parseInput(startText, endText, props) : null;
  const inputError = parsedDraft?.error ?? null;
  const startUnlimited = Boolean(unlimitedLabel && !inputError && !startText.trim() && endText.trim());
  const endUnlimited = Boolean(unlimitedLabel && !inputError && !endText.trim() && startText.trim());
  const unbounded: UnboundedBoundary = openRange && !pendingStart
    ? committedStart && !committedEnd ? 'end' : committedEnd && !committedStart ? 'start' : null
    : null;
  const errorText = inputError ? locale.errors[inputError] : '';
  const visibleError = showError && Boolean(inputError);
  const visualStatus = visibleError ? 'error' : status;
  const formatId = `${fieldId}-format`;
  const errorId = `${fieldId}-error`;
  const panelId = `${fieldId}-calendar`;
  const describedBy = [props['aria-describedby'], formatId, visibleError ? errorId : undefined].filter(Boolean).join(' ');
  const formatHint = timeZone ? `${format} (${timeZone})` : format;

  useEffect(() => {
    setDraft(null);
    setShowError(false);
  }, [committedStart, committedEnd, props.mode, editable]);

  useEffect(() => {
    startRef.current?.setCustomValidity(errorText);
    endRef.current?.setCustomValidity(errorText);
    onValidationChange?.(inputError);
  }, [errorText, inputError, onValidationChange]);

  useEffect(() => {
    if (!editable) setOpen(false);
  }, [editable]);

  function commit(start: string, end = '') {
    setDraft(null);
    setShowError(false);
    if (start === committedStart && end === committedEnd) return;
    if (props.mode === 'range' && props.allowOpenRange) {
      props.onChange(start || end ? [start || null, end || null] : null);
    } else if (props.mode === 'range') {
      props.onChange(start ? [start, end] : null);
    } else {
      props.onChange(start || null);
    }
  }

  function commitInput() {
    if (!parsedDraft) return true;
    if (parsedDraft.error) {
      setShowError(true);
      return false;
    }
    commit(parsedDraft.start, parsedDraft.end);
    return true;
  }

  function handleFieldBlur(event: FocusEvent<HTMLDivElement>) {
    const next = event.relatedTarget;
    if (groupRef.current?.contains(next) || panelRef.current?.contains(next)) return;
    commitInput();
  }

  function handleFieldKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (!editable || event.nativeEvent.isComposing) return;
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      openCalendar(event.currentTarget, true);
    } else if (event.key === 'Enter' && (draft || open)) {
      event.preventDefault();
      if (commitInput()) setOpen(false);
    }
  }

  function focusCalendar() {
    const selected = session?.focus && panelRef.current?.querySelector<HTMLButtonElement>(
      `[data-day="${session.focus}"]:not([data-outside]) button:not(:disabled)`,
    );
    const first = panelRef.current?.querySelector<HTMLElement>('[role="grid"] button[tabindex="0"]');
    (selected || first || panelRef.current)?.focus({ preventScroll: true });
  }

  function openCalendar(opener: HTMLElement | null, focusGrid: boolean, touch = false) {
    openerRef.current = opener;
    const field = touch ? touchFieldRef.current : opener;
    const boundary = canLeaveOpen && field === endRef.current ? 'end' : 'start';
    setActiveBoundary(boundary);
    if (open) {
      if (canLeaveOpen && boundary !== activeBoundary) commitInput();
      if (focusGrid) focusCalendar();
      return;
    }
    const today = currentDate(timeZone);
    const [start, end] = parsedDraft && !parsedDraft.error
      ? [parsedDraft.start, parsedDraft.end]
      : [committedStart, committedEnd];
    commitInput();
    const selected = boundary === 'end' ? end || start : start || end;
    const [selectedDay, selectedTime] = selected.split(' ');
    setSession({ ...initialCalendar(today, parseDateKey(selectedDay), props), today, touch });
    setPanelDay(selectedDay);
    setTimeParts(selectedTime?.split(':') ?? []);
    setPendingStart(undefined);
    setHoveredDay(undefined);
    focusGridOnOpen.current = focusGrid;
    restoreFocus.current = false;
    setOpen(true);
  }

  function handleFieldPointerDown(event: PointerEvent<HTMLDivElement>) {
    if (!editable || event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
    wasTouchPointer.current = event.pointerType === 'touch' || event.pointerType === 'pen';
    if (!wasTouchPointer.current) {
      focusFieldFromShell(event, startRef.current);
      return;
    }
    const active = document.activeElement;
    if (active === startRef.current || active === endRef.current) return;
    event.preventDefault();
    touchFieldRef.current = event.target instanceof HTMLInputElement ? event.target : startRef.current;
  }

  function finishPanel(start?: string, end?: string) {
    if (start !== undefined) commit(start, end);
    restoreFocus.current = true;
    setOpen(false);
  }

  function rangeWithSelectedDay(day: string): DatePickerOpenRange | undefined {
    if (pendingStart) return orderedRange(pendingStart, day);
    if (!canLeaveOpen) return;
    return activeBoundary === 'start' ? [day, committedEnd || null] : [committedStart || null, day];
  }

  function isUnavailable(day: string) {
    if (isDayUnavailable(day, props)) return true;
    const range = rangeWithSelectedDay(day);
    return Boolean(range?.[0] && range[1] && isRangeUnavailable(range, props));
  }

  function handleCalendarSelect(day: string) {
    if (isUnavailable(day)) return;
    if (isDateTime) {
      setPanelDay(day);
    } else if (isRange) {
      const range = rangeWithSelectedDay(day);
      if (range && !isRangeUnavailable(range, props)) finishPanel(range[0] ?? '', range[1] ?? '');
      else setPendingStart(day);
    } else {
      finishPanel(day);
    }
  }

  function handlePanelTab(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Tab') return;
    const stops = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button, select, input'))
      .filter((node) => node.tabIndex >= 0 && !node.matches(':disabled') && node.getClientRects().length > 0);
    const edge = event.shiftKey ? stops[0] : stops.at(-1);
    if (event.target === edge) {
      // Hand the next native Tab step back to the form's DOM order.
      openerRef.current?.focus({ preventScroll: true });
      setOpen(false);
    }
  }

  const hasContent = Boolean(startText || endText);
  const timeLabels = isDateTime && props.showSeconds ? [locale.hour, locale.minute, locale.second] : [locale.hour, locale.minute];
  const panelValue = isDateTime && panelDay
    ? parseInput(`${panelDay} ${timeLabels.map((_, index) => timeParts[index] ?? '').join(':')}`, '', props)
    : undefined;
  const presets = isRange ? props.presets?.filter(({ value: [start, end] }) => {
    const parsed = parseInput(start, end, props);
    return !parsed.error && Boolean(parsed.start && parsed.end);
  }) : undefined;

  return (
    <Popover.Root open={open && editable} onOpenChange={setOpen}>
      <div className={cn('w-full', className)}>
        <Popover.Anchor asChild>
          <div
            ref={groupRef}
            role={isRange ? 'group' : undefined}
            tabIndex={-1}
            aria-label={isRange ? props['aria-label'] : undefined}
            aria-labelledby={isRange ? props['aria-labelledby'] : undefined}
            className={cn(
              shellStyles({ size, state, status: visualStatus }),
              'overflow-visible outline-none',
              open && 'shadow-focus',
              open && visualStatus === 'default' && 'border-border-deep',
            )}
            onBlur={handleFieldBlur}
            onPointerDown={handleFieldPointerDown}
            onClick={(event) => {
              if (!editable || (event.target as HTMLElement).closest('button')) return;
              if (wasTouchPointer.current) {
                wasTouchPointer.current = false;
                const active = document.activeElement;
                if (active !== startRef.current && active !== endRef.current) {
                  event.preventDefault();
                  openCalendar(groupRef.current, true, true);
                }
                return;
              }
              const field = event.target instanceof HTMLInputElement ? event.target : startRef.current;
              openCalendar(field, false);
            }}
          >
            <div className={cn(CONTROL_ROW[size], 'coarse-pointer:gap-0 coarse-pointer:px-1')}>
              <input
                ref={startRef}
                id={props.id}
                role={editable ? 'combobox' : undefined}
                aria-haspopup={editable ? 'dialog' : undefined}
                aria-expanded={editable ? open : undefined}
                aria-controls={editable && open ? panelId : undefined}
                aria-label={isRange ? locale.startDate : props['aria-label']}
                aria-labelledby={isRange ? undefined : props['aria-labelledby']}
                aria-describedby={describedBy}
                aria-invalid={visualStatus === 'error' || undefined}
                className={cn(FIELD_BASE, 'tabular-nums', startUnlimited && 'placeholder:text-text-1')}
                autoComplete="off"
                placeholder={startUnlimited ? unlimitedLabel : isRange ? locale.startDate : format}
                disabled={disabled}
                readOnly={readOnly}
                value={startText}
                onChange={(event) => setDraft([event.target.value, endText])}
                onKeyDown={handleFieldKeyDown}
                onInvalid={() => setShowError(true)}
              />
              {isRange && (
                <>
                  <span aria-hidden className="text-text-3">–</span>
                  <input
                    ref={endRef}
                    role={editable ? 'combobox' : undefined}
                    aria-haspopup={editable ? 'dialog' : undefined}
                    aria-expanded={editable ? open : undefined}
                    aria-controls={editable && open ? panelId : undefined}
                    aria-label={locale.endDate}
                    aria-describedby={describedBy}
                    aria-invalid={visualStatus === 'error' || undefined}
                    className={cn(FIELD_BASE, 'tabular-nums', endUnlimited && 'placeholder:text-text-1')}
                    autoComplete="off"
                    placeholder={endUnlimited ? unlimitedLabel : locale.endDate}
                    disabled={disabled}
                    readOnly={readOnly}
                    value={endText}
                    onChange={(event) => setDraft([startText, event.target.value])}
                    onKeyDown={handleFieldKeyDown}
                    onInvalid={() => setShowError(true)}
                  />
                </>
              )}
              {editable && allowClear && (
                <button
                  type="button"
                  aria-label={locale.clear}
                  disabled={!hasContent}
                  className={cn(
                    FIELD_ACTION, ACTION_CLASS, 'text-text-4 hover:text-text-3 [&_svg]:size-3.5',
                    hasContent ? CLEAR_VISIBILITY : 'invisible',
                  )}
                  onClick={() => {
                    setOpen(false);
                    commit('');
                    startRef.current?.focus();
                  }}
                >
                  <Filled.CloseCircle aria-hidden />
                </button>
              )}
              {editable && (
                <span aria-hidden className="flex shrink-0 items-center text-text-3 coarse-pointer:px-2">
                  <Outlined.Calendar />
                </span>
              )}
            </div>
          </div>
        </Popover.Anchor>
        <span id={formatId} className={timeZone ? 'mt-1 block text-caption text-text-3' : 'sr-only'}>{formatHint}</span>
        {visibleError && <p id={errorId} role="alert" className="mt-1 text-caption text-danger">{errorText}</p>}
      </div>
      {session && (
        <Popover.Portal>
          <Popover.Content
            id={panelId}
            ref={panelRef}
            aria-label={locale.openCalendar}
            align="start"
            sideOffset={PANEL_SIDE_OFFSET}
            collisionPadding={phone ? 4 : PANEL_COLLISION_PADDING}
            className={panelSurfaceClass(DEFAULT_PANEL_RADIUS, 'flex max-h-[var(--radix-popover-content-available-height)] w-max max-w-[var(--radix-popover-content-available-width)] flex-col overflow-hidden')}
            onOpenAutoFocus={(event) => {
              event.preventDefault();
              if (focusGridOnOpen.current) focusCalendar();
            }}
            onInteractOutside={(event) => {
              if (groupRef.current?.contains(event.target as Node)) event.preventDefault();
            }}
            onEscapeKeyDown={() => { restoreFocus.current = true; }}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              if (restoreFocus.current) openerRef.current?.focus({ preventScroll: true });
              restoreFocus.current = false;
            }}
            onKeyDownCapture={handlePanelTab}
          >
            <div className="min-h-0 overflow-auto overscroll-contain p-3 coarse-pointer:max-[347px]:px-0">
              <DatePickerCalendar
                locale={locale}
                today={session.today}
                initialMonth={session.month}
                startMonth={session.min}
                endMonth={session.max}
                months={isRange && !phone && !compactTouch ? 2 : 1}
                selectedDay={isDateTime ? panelDay : committedStart}
                selectedEnd={isRange ? committedEnd : undefined}
                unbounded={unbounded}
                pendingStart={pendingStart}
                hoveredDay={hoveredDay}
                isUnavailable={isUnavailable}
                onSelect={handleCalendarSelect}
                onHover={setHoveredDay}
              />
              {!session.focus && (
                <p role="status" className="mt-2 px-1 text-caption text-text-3">{locale.errors.unavailable}</p>
              )}
              {pendingStart && (
                <div role="status" className="mt-2 px-1 text-caption text-text-3">
                  {locale.selectOtherDate}
                  {(props.mode === 'range' && (props.maxRangeDays !== undefined || props.isRangeDisabled)) && (
                    <p>{locale.rangeRestriction ?? locale.errors.unavailable}</p>
                  )}
                </div>
              )}
              {presets && presets.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1 border-t border-border-base pt-2">
                  {presets.map(({ label, value: [start, end] }) => (
                    <Button
                      key={label}
                      size="medium"
                      variant="text"
                      className="coarse-pointer:min-h-11"
                      onClick={() => {
                        const parsed = parseInput(start, end, props);
                        finishPanel(parsed.start, parsed.end);
                      }}
                    >
                      {label}
                    </Button>
                  ))}
                </div>
              )}
            </div>
            {session.touch && (
              <div className="flex shrink-0 justify-start border-t border-border-base px-3">
                <Button
                  size="medium"
                  variant="text"
                  className="min-h-11"
                  onClick={() => {
                    setOpen(false);
                    (touchFieldRef.current ?? startRef.current)?.focus();
                  }}
                >
                  {locale.enterDate}
                </Button>
              </div>
            )}
            {isDateTime && (
              <div className="shrink-0 space-y-2 border-t border-border-base px-3 py-2">
                <div className="flex gap-2">
                  {timeLabels.map((label, index) => (
                    <label key={index} className="min-w-0 flex-1 text-caption text-text-2">
                      {label}
                      <Input
                        inputMode="numeric"
                        placeholder="00"
                        value={timeParts[index] ?? ''}
                        className="coarse-pointer:h-11"
                        inputClassName="text-center tabular-nums"
                        onChange={(event) => {
                          const next = timeLabels.map((_, part) => part === index ? event.target.value : timeParts[part] ?? '');
                          setTimeParts(next);
                        }}
                      />
                    </label>
                  ))}
                </div>
                {panelValue?.error && timeLabels.every((_, index) => timeParts[index]) && (
                  <p role="status" className="text-caption text-danger">{locale.errors[panelValue.error]}</p>
                )}
                <div className="flex justify-end gap-2">
                  <Button variant="outlined" className="coarse-pointer:min-h-11" onClick={() => finishPanel()}>{locale.cancel}</Button>
                  <Button
                    disabled={!panelValue || Boolean(panelValue.error)}
                    className="coarse-pointer:min-h-11"
                    onClick={() => {
                      if (panelValue && !panelValue.error) finishPanel(panelValue.start);
                    }}
                  >
                    {locale.confirm}
                  </Button>
                </div>
              </div>
            )}
          </Popover.Content>
        </Popover.Portal>
      )}
    </Popover.Root>
  );
}
