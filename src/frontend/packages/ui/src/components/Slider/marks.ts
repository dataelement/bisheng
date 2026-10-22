import type * as React from 'react';

/**
 * Mark helpers for Slider (组件-Slider滑块.md §3.3). Pure functions so the
 * positioning maths — which has to agree with Radix's own thumb placement —
 * is in one place.
 */

/** §3.3 — the values to mark; a record also names each label. */
export type SliderMarks = number[] | Record<number, React.ReactNode>;

export interface NormalizedMark {
  value: number;
  /** `undefined` = fall back to `formatValue` / the plain number. */
  label: React.ReactNode | undefined;
}

export function normalizeMarks(marks: SliderMarks | undefined, min: number, max: number): NormalizedMark[] {
  if (!marks) return [];
  const list: NormalizedMark[] = Array.isArray(marks)
    ? marks.map((value) => ({ value, label: undefined }))
    : Object.entries(marks).map(([key, label]) => ({ value: Number(key), label }));
  return list
    .filter((mark) => Number.isFinite(mark.value) && mark.value >= min && mark.value <= max)
    .sort((a, b) => a.value - b.value);
}

export function toPercent(value: number, min: number, max: number): number {
  return max === min ? 0 : ((value - min) / (max - min)) * 100;
}

/** §4 — the thumb is 16px; half of it is how far Radix keeps the centre inside the track. */
const THUMB_HALF = 8;

/**
 * Radix keeps the thumb INSIDE the track: at 0% its centre sits 8px in, at
 * 100% 8px short of the end (getThumbInBoundsOffset). A mark has to use the
 * same offset or the dot under a resting thumb would be off by up to 8px.
 */
export function inBoundsLeft(percent: number): string {
  const offset = THUMB_HALF * (1 - percent / 50);
  return `calc(${percent}% + ${offset}px)`;
}

export function nearestMark(value: number, marks: NormalizedMark[]): number {
  let best = marks[0].value;
  for (const mark of marks) {
    if (Math.abs(mark.value - value) < Math.abs(best - value)) best = mark.value;
  }
  return best;
}

/** The mark one step to the left / right of `value` (keyboard in snap mode). */
export function adjacentMark(value: number, direction: 1 | -1, marks: NormalizedMark[]): number {
  const index = marks.findIndex((mark) => mark.value === nearestMark(value, marks));
  const next = Math.min(marks.length - 1, Math.max(0, index + direction));
  return marks[next].value;
}
