import { Outlined } from 'bisheng-icons';
import { createContext, useContext, type ComponentProps } from 'react';
import { Day, DayButton, DayPicker, MonthCaption, TZDate, useDayPicker, type Chevron, type DayPickerProps, type DropdownProps } from 'react-day-picker';
import cn from '../../utils/cn';
import { Button } from '../Button/Button';
import { Select } from '../Select/Select';
import { calendarDate, dateKey, orderedRange, parseDateKey, type UnboundedBoundary } from './dates';
import type { DatePickerLocale } from './types';

const NAV_BUTTON =
  'pointer-events-auto grid size-8 place-items-center rounded-md text-text-2 hover:bg-fill-2 ' +
  'coarse-pointer:size-11 coarse-pointer:active:bg-fill-2 aria-disabled:opacity-40 aria-disabled:hover:bg-transparent';

const calendarClasses: DayPickerProps['classNames'] = {
  months: 'relative flex w-max gap-3 text-control',
  month: 'w-[252px] coarse-pointer:w-[308px]',
  nav: 'pointer-events-none absolute inset-x-0 top-0 z-10 flex justify-between',
  button_previous: NAV_BUTTON,
  button_next: NAV_BUTTON,
  month_caption: 'flex h-8 items-center justify-center coarse-pointer:h-11',
  dropdowns: 'flex items-center justify-center gap-1',
  month_grid: 'w-full table-fixed border-collapse',
  weekday: 'h-8 text-center text-caption font-normal text-text-3',
  day: 'relative p-0 text-center',
  outside: 'text-text-2',
  disabled: 'text-text-4',
};

function CalendarChevron({ orientation, className }: ComponentProps<typeof Chevron>) {
  const Icon = orientation === 'left' ? Outlined.Left : Outlined.Right;
  return <Icon aria-hidden className={cn('size-4', className)} />;
}

const CaptionDate = createContext<Date | null>(null);

function CalendarMonthCaption(props: ComponentProps<typeof MonthCaption>) {
  return (
    <CaptionDate.Provider value={props.calendarMonth.date}>
      <MonthCaption {...props} />
    </CaptionDate.Provider>
  );
}

function CalendarCaptionSelect({ unit, value, options = [], disabled, 'aria-label': label }: DropdownProps & { unit: 'month' | 'year' }) {
  const { goToMonth } = useDayPicker();
  const date = useContext(CaptionDate);
  if (!date) return null;

  const selectedLabel = options.find((option) => option.value === value)?.label;
  return (
    <Select
      value={typeof value === 'number' ? value : null}
      options={options}
      disabled={disabled}
      aria-label={[label, selectedLabel].filter(Boolean).join(' ')}
      panelClassName="min-w-28 max-h-[min(296px,var(--radix-popover-content-available-height))]"
      onChange={(next) => {
        if (typeof next !== 'number') return;
        const year = unit === 'year' ? next : date.getUTCFullYear();
        const month = unit === 'month' ? next : date.getUTCMonth();
        goToMonth(new TZDate(calendarDate(year, month + 1, 1).getTime(), 'UTC'));
      }}
      trigger={
        <Button
          type="button"
          variant="text"
          color="default"
          disabled={disabled}
          className="group/caption gap-0.5 px-1 font-medium text-text-1 [&_svg]:size-3 coarse-pointer:min-h-11 coarse-pointer:min-w-11"
        >
          {selectedLabel}
          <Outlined.Down aria-hidden className="group-data-[menu-open]/caption:rotate-180" />
        </Button>
      }
    />
  );
}

function CalendarMonthsDropdown(props: DropdownProps) {
  return <CalendarCaptionSelect {...props} unit="month" />;
}

function CalendarYearsDropdown(props: DropdownProps) {
  return <CalendarCaptionSelect {...props} unit="year" />;
}

function CalendarCell({ day, modifiers, className, ...props }: ComponentProps<typeof Day>) {
  const inMonth = !day.outside;
  const selected = inMonth && modifiers.selected ? true : undefined;
  return (
    <Day
      {...props}
      day={day}
      modifiers={modifiers}
      aria-selected={selected}
      data-selected={selected}
      className={cn(className, inMonth && (modifiers.range_middle || modifiers.unbounded_range) && 'bg-blue-50')}
    />
  );
}

function CalendarDay({ day, modifiers, ...props }: ComponentProps<typeof DayButton>) {
  const inMonth = !day.outside;
  const selected = inMonth && modifiers.selected && !modifiers.range_middle;
  const rangeStart = modifiers.unbounded_start || modifiers.preview_start || (modifiers.range_start && !modifiers.range_end);
  const rangeEnd = modifiers.unbounded_end || modifiers.preview_end || (modifiers.range_end && !modifiers.range_start);
  return (
    <DayButton
      {...props}
      day={day}
      modifiers={modifiers}
      className={cn(
        'relative grid aspect-square w-full place-items-center tabular-nums',
        'focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-current',
        'disabled:cursor-not-allowed',
        selected
          ? 'border border-blue-500 bg-blue-100'
          : !modifiers.disabled && 'hover:bg-fill-2 coarse-pointer:active:bg-fill-2',
        selected && (rangeStart ? 'rounded-l-md rounded-r-none' : rangeEnd ? 'rounded-r-md rounded-l-none' : 'rounded-md'),
        inMonth && modifiers.preview && 'bg-blue-50',
        inMonth && modifiers.today && 'after:absolute after:bottom-0.5 after:size-1 after:rounded-full after:bg-blue-500',
      )}
    />
  );
}

interface DatePickerCalendarProps {
  locale: DatePickerLocale;
  today: Date;
  initialMonth: Date;
  startMonth: Date;
  endMonth: Date;
  months: number;
  selectedDay: string;
  selectedEnd?: string;
  unbounded: UnboundedBoundary;
  pendingStart?: string;
  hoveredDay?: string;
  isUnavailable: (day: string) => boolean;
  onSelect: (day: string) => void;
  onHover: (day?: string) => void;
}

export function DatePickerCalendar({
  locale, today, initialMonth, startMonth, endMonth, months, selectedDay, selectedEnd, unbounded, pendingStart,
  hoveredDay, isUnavailable, onSelect, onHover,
}: DatePickerCalendarProps) {
  const preview = pendingStart && hoveredDay && !isUnavailable(hoveredDay)
    ? orderedRange(pendingStart, hoveredDay)
    : undefined;
  const hasPreviewSpan = preview !== undefined && preview[0] !== preview[1];
  const finiteBoundary = unbounded === 'start' ? selectedEnd : selectedDay;
  const common: DayPickerProps = {
    timeZone: 'UTC',
    today,
    defaultMonth: initialMonth,
    startMonth,
    endMonth,
    numberOfMonths: months,
    locale: locale.calendar,
    labels: {
      ...locale.calendarLabels,
      labelDayButton: (date, modifiers, ...args) => locale.calendarLabels.labelDayButton(
        date, modifiers.outside ? { ...modifiers, selected: false, today: false } : modifiers, ...args,
      ),
    },
    captionLayout: 'dropdown',
    fixedWeeks: true,
    showOutsideDays: true,
    classNames: calendarClasses,
    components: {
      Chevron: CalendarChevron,
      Day: CalendarCell,
      DayButton: CalendarDay,
      MonthCaption: CalendarMonthCaption,
      MonthsDropdown: CalendarMonthsDropdown,
      YearsDropdown: CalendarYearsDropdown,
    },
    disabled: (day) => isUnavailable(dateKey(day)),
    modifiers: {
      unbounded_start: (day) => unbounded === 'end' && dateKey(day) === finiteBoundary,
      unbounded_end: (day) => unbounded === 'start' && dateKey(day) === finiteBoundary,
      unbounded_range: (day) => {
        if (!finiteBoundary) return false;
        const key = dateKey(day);
        return unbounded === 'start' ? key < finiteBoundary : unbounded === 'end' && key > finiteBoundary;
      },
      preview_start: (day) => hasPreviewSpan && dateKey(day) === preview[0],
      preview_end: (day) => hasPreviewSpan && dateKey(day) === preview[1],
      preview: (day) => {
        if (!preview) return false;
        const key = dateKey(day);
        return key >= preview[0] && key <= preview[1] && key !== pendingStart;
      },
    },
    onDayMouseEnter: (day) => {
      if (pendingStart && window.matchMedia('(hover: hover) and (pointer: fine)').matches) onHover(dateKey(day));
    },
    onDayMouseLeave: () => onHover(),
  };

  const selected = parseDateKey(pendingStart ?? (unbounded ? finiteBoundary ?? '' : selectedDay));
  if (selectedEnd !== undefined) {
    return (
      <DayPicker
        {...common}
        mode="range"
        required
        selected={selected ? { from: selected, to: unbounded ? selected : pendingStart ? undefined : parseDateKey(selectedEnd) } : undefined}
        onSelect={(_, day) => onSelect(dateKey(day))}
      />
    );
  }

  return <DayPicker {...common} mode="single" required selected={selected} onSelect={(_, day) => onSelect(dateKey(day))} />;
}
