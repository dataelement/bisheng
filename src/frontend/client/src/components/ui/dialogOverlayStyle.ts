import type { CSSProperties } from 'react';
import { isDesktopEmbedded } from '../Chat/desktopEmbedding';

/** Desktop body portals dim the native viewport while Radix owns modal interaction. */
export function dialogOverlayStyle(style?: CSSProperties): CSSProperties | undefined {
  return isDesktopEmbedded() ? { ...style, background: 'rgba(0, 0, 0, 0.4)' } : style;
}
