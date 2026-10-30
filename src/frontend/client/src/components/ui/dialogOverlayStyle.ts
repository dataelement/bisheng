import type { CSSProperties } from 'react';
import { isDesktopEmbedded } from '../Chat/desktopEmbedding';

/** Desktop dialogs preserve the page colors while Radix owns modal interaction. */
export function dialogOverlayStyle(style?: CSSProperties): CSSProperties | undefined {
  return isDesktopEmbedded() ? { ...style, background: 'transparent' } : style;
}
