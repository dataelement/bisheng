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
 * NOTE: this uses the tailwind-merge **v1.x** config shape (`classGroups` at the
 * top level). v2+ nests it under `extend` — do not copy a v2 snippet here while
 * the dependency is pinned to ^1.14.0 (kept in the workspace catalog).
 */
const twMerge = extendTailwindMerge({
  classGroups: {
    'font-size': [
      { text: ['caption', 'body-sm', 'body', 'h1', 'h2', 'h3', 'h4', 'display', 'metric'] },
    ],
  },
});

/**
 * Merges the tailwind classes (using twMerge). Conditionally removes false values
 * @param inputs The tailwind classes to merge
 * @returns className string to apply to an element or HOC
 */
export default function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
