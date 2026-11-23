import type { DatePickerError, DatePickerOpenRange, DatePickerProps, DatePickerRange } from './types';

export type UnboundedBoundary = 'start' | 'end' | null;

const DAY_MS = 86_400_000;

// UTC is only the arithmetic coordinate system for civil dates. Values travel
// as calendar strings or wall-clock strings, without any timestamp conversion.
export function calendarDate(year: number, month: number, day: number): Date {
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1, day);
  return date;
}

export function dateKey(date: Date): string {
  const year = String(date.getUTCFullYear()).padStart(4, '0');
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function parseDateKey(text: string): Date | undefined {
  const match = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(text.trim());
  if (!match) return;
  const [, year, month, day] = match.map(Number);
  const date = calendarDate(year, month, day);
  if (year > 0 && date.getUTCFullYear() === year && date.getUTCMonth() + 1 === month && date.getUTCDate() === day) {
    return date;
  }
}

export function currentDate(timeZone?: string): Date {
  const now = new Date();
  if (!timeZone) return calendarDate(now.getFullYear(), now.getMonth() + 1, now.getDate());
  const parts = new Intl.DateTimeFormat('en', {
    year: 'numeric', month: 'numeric', day: 'numeric', timeZone,
  }).formatToParts(now);
  const part = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((item) => item.type === type)?.value);
  return calendarDate(part('year'), part('month'), part('day'));
}

export function isDayUnavailable(date: string, props: DatePickerProps): boolean {
  return Boolean(
    (props.minDate && date < props.minDate) ||
    (props.maxDate && date > props.maxDate) ||
    props.isDateDisabled?.(date),
  );
}

export function orderedRange(first: string, second: string): DatePickerRange {
  return first <= second ? [first, second] : [second, first];
}

export function isRangeUnavailable(range: DatePickerOpenRange, props: DatePickerProps): boolean {
  if (props.mode !== 'range') return false;
  const [start, end] = range;
  if (!start && !end) return true;
  if ((start && isDayUnavailable(start, props)) || (end && isDayUnavailable(end, props))) return true;
  if ((!start || !end) && (!props.allowOpenRange || props.maxRangeDays !== undefined)) return true;
  if (start && end && start > end) return true;
  if (props.maxRangeDays !== undefined) {
    const startDay = parseDateKey(start ?? '');
    const endDay = parseDateKey(end ?? '');
    if (!startDay || !endDay || (endDay.getTime() - startDay.getTime()) / DAY_MS + 1 > props.maxRangeDays) return true;
  }
  if (props.allowOpenRange) return Boolean(props.isRangeDisabled?.(range));
  return Boolean(start && end && props.isRangeDisabled?.([start, end]));
}

export function parseTime(text: string, showSeconds: boolean): string | undefined {
  const parts = text.split(':');
  const limits = showSeconds ? [23, 59, 59] : [23, 59];
  if (parts.length !== limits.length || parts.some((part, i) => !/^\d{1,2}$/.test(part) || Number(part) > limits[i])) return;
  return parts.map((part) => part.padStart(2, '0')).join(':');
}

interface ParsedInput {
  start: string;
  end: string;
  error: DatePickerError | null;
}

export function parseInput(startText: string, endText: string, props: DatePickerProps): ParsedInput {
  const result: ParsedInput = { start: '', end: '', error: null };
  const hasStart = Boolean(startText.trim());
  const hasEnd = Boolean(endText.trim());
  if (!hasStart && !hasEnd) return result;

  const parts = startText.trim().split(/\s+/);
  const startDate = parseDateKey(parts[0]);
  const endDate = parseDateKey(endText);
  if (props.mode === 'range') {
    if ((!hasStart || !hasEnd) && (!props.allowOpenRange || props.maxRangeDays !== undefined)) {
      result.error = 'incompleteRange';
    } else if ((hasStart && (!startDate || parts.length !== 1)) || (hasEnd && !endDate)) {
      result.error = 'invalidDate';
    } else {
      result.start = startDate ? dateKey(startDate) : '';
      result.end = endDate ? dateKey(endDate) : '';
      if (result.start && result.end && result.end < result.start) result.error = 'reversedRange';
      else if (isRangeUnavailable([result.start || null, result.end || null], props)) result.error = 'unavailable';
    }
  } else if (!startDate || (props.mode !== 'datetime' && parts.length !== 1)) {
    result.error = 'invalidDate';
  } else {
    result.start = dateKey(startDate);
    if (props.mode === 'datetime') {
      const time = parts.length === 2 ? parseTime(parts[1], Boolean(props.showSeconds)) : undefined;
      if (!time) {
        result.error = 'invalidTime';
      } else {
        result.start += ` ${time}`;
        if (isDayUnavailable(dateKey(startDate), props) || props.isDateTimeDisabled?.(result.start)) {
          result.error = 'unavailable';
        }
      }
    } else if (isDayUnavailable(result.start, props)) {
      result.error = 'unavailable';
    }
  }
  return result;
}

export function initialCalendar(today: Date, selected: Date | undefined, props: DatePickerProps) {
  const target = selected ?? today;
  const year = target.getUTCFullYear();
  const min = parseDateKey(props.minDate ?? '') ?? calendarDate(Math.max(1, year - 100), 1, 1);
  const max = parseDateKey(props.maxDate ?? '') ?? calendarDate(Math.min(9999, year + 100), 12, 31);
  const first = min.getTime();
  const last = max.getTime();
  if (first > last) return { min, max: min, month: min, focus: undefined };

  const center = Math.max(first, Math.min(last, target.getTime()));
  const month = new Date(center);
  if (selected && center === selected.getTime() && !isDayUnavailable(dateKey(selected), props)) {
    return { min, max, month, focus: dateKey(selected) };
  }
  const maxDistance = Math.max(center - first, last - center);
  for (let distance = 0; distance <= maxDistance; distance += DAY_MS) {
    const candidates = distance ? [center - distance, center + distance] : [center];
    for (const time of candidates) {
      if (time < first || time > last) continue;
      const day = new Date(time);
      const key = dateKey(day);
      if (!isDayUnavailable(key, props)) return { min, max, month: day, focus: key };
    }
  }
  return { min, max, month, focus: undefined };
}
