/**
 * execTokens — single source of truth for the task-mode "Cockpit × Narrative"
 * design tokens (《灵思任务模式执行流重构-最终落地规格》§1.1) plus the activity
 * category → i18n-key map (§3). Every Execution/ component imports its colors and
 * activity labels from here so the palette never drifts and the old
 * invisible-icon grey is fully eliminated.
 *
 * Pure constants — no imports / side effects / HTTP (constitution C7 safe).
 */
import type { ActivityCategory } from './stepUtils';

// ── Cockpit palette (§1.1) ──────────────────────────────────────────────────
/** Ink (主墨): narration hero, done group titles, result body. */
export const INK = '#1D2129';
/** Muted (次级): activity meta, timing, done icons, collapsed secondary info. */
export const MUTED = '#8A8A8A';
/** Faint (极弱): separators / placeholders — replaces the old invisible grey. */
export const FAINT = '#BFBFBF';
/** Accent (唯一强调蓝): RUNNING only — live dot/spinner/timer/scan ridge. */
export const ACCENT = '#2D6BFF';
/** Body (正文灰): expanded thinking body (one notch darker than old #818181). */
export const BODY = '#5C5C5C';
/** Surface (面板底): subagent monitor panel ground, file-card ground. */
export const SURFACE = '#FAFBFC';
/** Hairline: 1px panel/card borders, peak-end separators (2px Ink at the end). */
export const HAIRLINE = '#E8EAED';

// ── Activity category → i18n key (§3) ───────────────────────────────────────
/**
 * Maps each summarizeActivity category to its localized "动作摘要" phrase key.
 * Each phrase carries a single `{{0}}` count placeholder. Components render via
 * `localize(ACTIVITY_I18N[category], String(count))`.
 */
export const ACTIVITY_I18N: Record<ActivityCategory, string> = {
    web_search: 'com_linsight_act_web_search',
    knowledge: 'com_linsight_act_knowledge',
    read_file: 'com_linsight_act_read_file',
    write_file: 'com_linsight_act_write_file',
    export: 'com_linsight_act_export',
    code: 'com_linsight_act_code',
    browse: 'com_linsight_act_browse',
    other: 'com_linsight_act_other',
};

// ── card texture re-exports ─────────────────────────────────────────────────
/**
 * Re-export the card texture tokens so callers can pull every shared token from
 * one module. The definitions stay in cardTexture.ts (no current consumer after
 * the R3 完全拆平 refactor removed the subagent cards — kept for future reuse).
 */
export { DOT_BG, SHEEN } from './cardTexture';
