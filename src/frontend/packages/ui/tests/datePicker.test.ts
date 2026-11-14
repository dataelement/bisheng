import assert from 'node:assert/strict';
import { test } from 'node:test';
import { enUS } from 'react-day-picker/locale';
import { isRangeUnavailable, parseInput } from '../src/components/DatePicker/dates.ts';
import type { DatePickerOpenRange, DatePickerOpenRangeLocale, DatePickerProps, DatePickerRange } from '../src/components/DatePicker/types.ts';

const locale: DatePickerOpenRangeLocale = {
  calendar: enUS,
  openCalendar: 'Open calendar', enterDate: 'Enter date', clear: 'Clear',
  startDate: 'Start', endDate: 'End', selectOtherDate: 'Choose another date',
  unlimited: 'Unlimited',
  cancel: 'Cancel', confirm: 'Confirm', hour: 'Hour', minute: 'Minute', second: 'Second',
  calendarLabels: {
    labelNav: () => 'Navigation',
    labelPrevious: () => 'Previous', labelNext: () => 'Next',
    labelMonthDropdown: () => 'Month', labelYearDropdown: () => 'Year',
    labelDayButton: (date) => date.toISOString().slice(0, 10),
  },
  errors: {
    invalidDate: 'Invalid date', invalidTime: 'Invalid time', incompleteRange: 'Incomplete range',
    reversedRange: 'Reversed range', unavailable: 'Unavailable',
  },
};

const closed: DatePickerProps = { mode: 'range', value: null, onChange: () => {}, locale };
const openRange: DatePickerProps = { mode: 'range', allowOpenRange: true, value: null, onChange: () => {}, locale };

test('a missing endpoint is incomplete when the picker requires a finite range', () => {
  for (const props of [closed, { ...openRange, maxRangeDays: 7 }]) {
    assert.equal(parseInput('2026-11-11', '', props).error, 'incompleteRange');
    assert.equal(parseInput('', '2026-11-11', props).error, 'incompleteRange');
  }
});

test('open ranges accept either empty endpoint and validate all entered dates', () => {
  assert.deepEqual(parseInput('2026-11-1', '', openRange), { start: '2026-11-01', end: '', error: null });
  assert.deepEqual(parseInput(' ', '2024-2-29', openRange), { start: '', end: '2024-02-29', error: null });
  assert.deepEqual(parseInput('2026-11-11', '2026-11-12', openRange), { start: '2026-11-11', end: '2026-11-12', error: null });
  assert.equal(parseInput('', '2025-2-29', openRange).error, 'invalidDate');
  assert.equal(parseInput('2026-11-12', '2026-11-11', openRange).error, 'reversedRange');
  assert.equal(isRangeUnavailable([null, null], openRange), true);
  assert.deepEqual(parseInput('', '', openRange), { start: '', end: '', error: null });
});

test('date limits and maximum span also constrain unbounded ranges', () => {
  assert.equal(isRangeUnavailable([null, '2026-11-10'], { ...openRange, minDate: '2026-11-11' }), true);
  assert.equal(isRangeUnavailable(['2026-11-12', null], { ...openRange, maxDate: '2026-11-11' }), true);
  assert.equal(isRangeUnavailable(['2026-11-11', null], { ...openRange, maxRangeDays: 7 }), true);
  assert.equal(isRangeUnavailable([null, '2026-11-11'], { ...openRange, maxRangeDays: 7 }), true);
  assert.equal(isRangeUnavailable(['2026-11-11', '2026-11-17'], { ...openRange, maxRangeDays: 7 }), false);
  assert.equal(isRangeUnavailable(['2026-11-11', '2026-11-18'], { ...openRange, maxRangeDays: 7 }), true);
});

test('business validation receives the explicit null endpoint', () => {
  const received: DatePickerOpenRange[] = [];
  const props: DatePickerProps = {
    ...openRange,
    isRangeDisabled: (range: DatePickerOpenRange) => {
      received.push(range);
      return range[1] === null;
    },
  };
  assert.equal(parseInput('2026-11-11', '', props).error, 'unavailable');
  assert.equal(parseInput('', '2026-11-11', props).error, null);
  assert.deepEqual(received, [['2026-11-11', null], [null, '2026-11-11']]);
});

test('closed ranges keep date parsing, ordering and callback types', () => {
  const props: DatePickerProps = {
    mode: 'range', value: null, onChange: () => {}, locale,
    isRangeDisabled: ([start, end]: DatePickerRange) => start.slice(0, 4) !== end.slice(0, 4),
  };
  assert.deepEqual(parseInput('2026-11-1', '2026-11-2', props), { start: '2026-11-01', end: '2026-11-02', error: null });
  assert.equal(parseInput('2026-11-2', '2026-11-1', props).error, 'reversedRange');
  assert.equal(parseInput('2026-11-1 extra', '2026-11-2', props).error, 'invalidDate');
  assert.equal(parseInput('2026-12-31', '2027-01-01', props).error, 'unavailable');
  assert.equal(isRangeUnavailable(['2026-11-11', null], props), true);
});
