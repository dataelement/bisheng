/**
 * Pure number helpers for InputNumber (组件-InputNumber数字输入框.md §4).
 *
 * Kept apart from the component so the "never change the user's value" rules
 * (§4.2) read as plain functions: parsing, validation and stepping never round
 * or clamp what the user typed — only a step the user asked for is clamped.
 */

/** Why the current value cannot be submitted (§5.2). */
export type InputNumberErrorType = 'range' | 'precision';

/** §5.2 — everything a caller needs to write「请输入 1～100 之间的数」in its own locale. */
export interface InputNumberError {
  type: InputNumberErrorType;
  min?: number;
  max?: number;
  precision: number;
}

/** Decimal places of a number as written, e.g. 0.25 → 2, 1e-7 → 7. */
export function countDecimals(value: number): number {
  if (!Number.isFinite(value)) return 0;
  const text = String(value);
  const exp = text.match(/e-(\d+)$/);
  if (exp) {
    const mantissa = text.slice(0, text.indexOf('e'));
    const dot = mantissa.indexOf('.');
    return Number(exp[1]) + (dot === -1 ? 0 : mantissa.length - dot - 1);
  }
  const dot = text.indexOf('.');
  return dot === -1 ? 0 : text.length - dot - 1;
}

/** Decimal places of the text in the box — "1.50" counts 2, unlike `countDecimals(1.5)`. */
function countTextDecimals(text: string): number {
  const dot = text.indexOf('.');
  return dot === -1 ? 0 : text.length - dot - 1;
}

/**
 * §4.2 — what may be typed at all: digits, one dot, and a leading minus only
 * when negatives are possible. Returns the cleaned text, or `null` to reject
 * the keystroke. Thousands separators are dropped so a pasted「1,000」lands.
 */
export function sanitizeInput(raw: string, allowNegative: boolean): string | null {
  const text = raw.replace(/,/g, '').trim();
  const pattern = allowNegative ? /^-?\d*\.?\d*$/ : /^\d*\.?\d*$/;
  return pattern.test(text) ? text : null;
}

/** Empty / half-typed text ("-", ".") is "no value", not 0 (§4.2「清空就是空」). */
export function parseText(text: string): number | null {
  if (text === '' || text === '-' || text === '.' || text === '-.') return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/** §4.1 — display pads to precision (1 → 1.00); it never rounds a longer value. */
export function formatValue(value: number, precision: number): string {
  if (countDecimals(value) > precision) return String(value);
  return value.toFixed(precision);
}

/** §5.2 — range first: "out of range" is the more useful thing to fix. */
export function validate(
  text: string,
  { min, max, precision }: { min?: number; max?: number; precision: number },
): InputNumberError | null {
  const value = parseText(text);
  if (value === null) return null;
  if ((min !== undefined && value < min) || (max !== undefined && value > max)) {
    return { type: 'range', min, max, precision };
  }
  // A trailing "1." or padded "1.00" is still within precision 0 / 2 by value.
  const trimmed = text.includes('.') ? text.replace(/0+$/, '').replace(/\.$/, '') : text;
  if (countTextDecimals(trimmed) > precision) return { type: 'precision', min, max, precision };
  return null;
}

/**
 * §5.2 / 落地 5 — one step, in scaled integers so 0.1 + 0.2 is 0.3. An
 * out-of-range value first lands on the nearest bound (a step the user asked
 * for, so it is not "changing their value"); otherwise the result is clamped.
 */
export function stepValue(
  current: number | null,
  delta: number,
  { min, max }: { min?: number; max?: number },
): number {
  if (current !== null) {
    if (max !== undefined && current > max) return max;
    if (min !== undefined && current < min) return min;
  }
  const base = current ?? 0;
  const scale = 10 ** Math.max(countDecimals(base), countDecimals(delta));
  let next = (Math.round(base * scale) + Math.round(delta * scale)) / scale;
  if (max !== undefined && next > max) next = max;
  if (min !== undefined && next < min) next = min;
  return next;
}
