/**
 * Shared card-texture tokens for task-mode subagent cards — the single source of
 * truth so SubagentTrack and any future polished card stay byte-identical.
 *
 * Both tokens are extracted verbatim from the merged-out colleague card
 * SubagentRow (3ceecea64), itself sourced from the clarification card
 * (ClarifyCard:161). ClarifyCard keeps its own inline copy (do NOT touch its
 * bytes); this module is the reuse point for the Execution subagent surface.
 *
 * No imports / side effects / HTTP — pure constants (constitution C7 safe).
 */
import type { CSSProperties } from 'react';

/** Dotted base texture: white ground + a 5px-tiled SVG with a faint #EAEEFF dot.
 *  Reused verbatim from ClarifyCard / SubagentRow (3ceecea64). */
export const DOT_BG: CSSProperties = {
    backgroundColor: '#FFFFFF',
    backgroundImage:
        'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'5\' height=\'5\'%3E%3Ccircle cx=\'0.5\' cy=\'0.5\' r=\'0.5\' fill=\'%23EAEEFF\'/%3E%3C/svg%3E")',
    backgroundSize: '5px 5px',
};

/** Diagonal glint overlaid on the dotted base (Figma 12221:40064). A soft grey
 *  streak on its own layer; the `animate-sheen-sweep` keyframe slides it across
 *  the card (clipped by the card's overflow-hidden) so the gradient flows. A
 *  plain white streak is invisible on the near-white card, so it carries a light
 *  grey cast to read as motion. Reused verbatim from SubagentRow (3ceecea64). */
export const SHEEN =
    'linear-gradient(120deg, transparent 0%, rgba(140,140,140,0.025) 28%, rgba(140,140,140,0.09) 50%, rgba(140,140,140,0.025) 72%, transparent 100%)';
