import type { DayPickerProps, Labels } from 'react-day-picker';
import type { InputSize, InputStatus } from '../Input/shared';

/** Inclusive Gregorian calendar dates, formatted as YYYY-MM-DD. */
export type DatePickerRange = readonly [start: string, end: string];
/** An empty endpoint is represented by null. At least one date is required. */
export type DatePickerOpenRange = readonly [start: string | null, end: string | null];

export type DatePickerError = 'invalidDate' | 'invalidTime' | 'incompleteRange' | 'reversedRange' | 'unavailable';

export interface DatePickerLocale {
  calendar: NonNullable<DayPickerProps['locale']>;
  openCalendar: string;
  enterDate: string;
  clear: string;
  startDate: string;
  endDate: string;
  selectOtherDate: string;
  rangeRestriction?: string;
  cancel: string;
  confirm: string;
  hour: string;
  minute: string;
  second: string;
  errors: Record<DatePickerError, string>;
  /** Translated calendar announcements and navigation names. */
  calendarLabels: Pick<Labels, 'labelDayButton' | 'labelNav' | 'labelPrevious' | 'labelNext' | 'labelMonthDropdown' | 'labelYearDropdown'>;
}

export interface DatePickerOpenRangeLocale extends DatePickerLocale {
  unlimited: string;
}

interface DatePickerBaseProps {
  /** ID for the first field and its external label. */
  id?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  'aria-describedby'?: string;
  className?: string;
  size?: InputSize;
  status?: InputStatus;
  disabled?: boolean;
  readOnly?: boolean;
  allowClear?: boolean;
  minDate?: string;
  maxDate?: string;
  isDateDisabled?: (date: string) => boolean;
  locale: DatePickerLocale;
  onValidationChange?: (error: DatePickerError | null) => void;
}

interface SingleDatePickerProps extends DatePickerBaseProps {
  mode?: 'date';
  value: string | null;
  onChange: (value: string | null) => void;
}

interface DateRangeBaseProps extends DatePickerBaseProps {
  mode: 'range';
  maxRangeDays?: number;
  presets?: readonly { label: string; value: DatePickerRange }[];
}

interface DateRangePickerProps extends DateRangeBaseProps {
  allowOpenRange?: false;
  value: DatePickerRange | null;
  onChange: (value: DatePickerRange | null) => void;
  isRangeDisabled?: (range: DatePickerRange) => boolean;
}

interface OpenDateRangePickerProps extends DateRangeBaseProps {
  allowOpenRange: true;
  value: DatePickerOpenRange | null;
  onChange: (value: DatePickerOpenRange | null) => void;
  isRangeDisabled?: (range: DatePickerOpenRange) => boolean;
  locale: DatePickerOpenRangeLocale;
}

interface DateTimePickerProps extends DatePickerBaseProps {
  mode: 'datetime';
  /** Local wall-clock time, formatted as YYYY-MM-DD HH:mm[:ss]. */
  value: string | null;
  onChange: (value: string | null) => void;
  showSeconds?: boolean;
  /** IANA time zone used to determine today and label the wall-clock value. */
  timeZone?: string;
  isDateTimeDisabled?: (value: string) => boolean;
}

export type DatePickerProps = SingleDatePickerProps | DateRangePickerProps | OpenDateRangePickerProps | DateTimePickerProps;
