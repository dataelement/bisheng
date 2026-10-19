import { extendTailwindMerge } from 'tailwind-merge';
import { type ClassValue, clsx } from 'clsx';

/**
 * twMerge taught about the design system's semantic font-size tokens
 * (基础-字体规范.md §7 / fontSize in tailwind-preset.cjs).
 *
 * Why this is required: tailwind-merge's `text-*` handling treats any UNKNOWN
 * `text-X` as a text COLOR (catch-all). So `text-body` / `text-h1` / `text-caption`
 * … are mis-grouped as colors, and when a real color appears in the SAME cn()
 * call, the font size is silently dropped → element falls back to the inherited
 * 16px. Registering them in the `font-size` group makes cn() preserve size +
 * color together, and collapse size-vs-size correctly.
 *
 * Support both v1's top-level classGroups and v2's nested extend.classGroups.
 * Source-shipped consumers can prebundle our import with their own v2 copy
 * (platform does this in Vite), even though the workspace catalog pins v1.
 */
const classGroups = {
  'font-size': [
    { text: ['caption-sm', 'caption', 'body-sm', 'body', 'h1', 'h2', 'h3', 'h4', 'display', 'metric'] },
  ],
};
const mergeConfig = { classGroups, extend: { classGroups } };
const twMerge = extendTailwindMerge(mergeConfig);

/**
 * Merges the tailwind classes (using twMerge). Conditionally removes false values
 * @param inputs The tailwind classes to merge
 * @returns className string to apply to an element or HOC
 */
export default function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
