/**
 * Brand-themed empty-state / status illustrations.
 *
 * Each is an inline SVG React component whose brand greens re-point to the
 * `--illus-*` palette (a separate, brighter ramp than the UI brand colors), so
 * they follow the blue ⇄ green theme switch. Passing `grey` renders the
 * theme-independent grey draft. Palette + rules: 基础-色彩规范 §5 /
 * docs/components/illustration.mdx.
 *
 * Presentation-only: props in, SVG out — no store, no i18n, no routing.
 */
import type { SVGProps } from 'react';

/** Shared shape of every illustration: any SVG prop, plus the grey-draft flag. */
export type IllustrationProps = SVGProps<SVGSVGElement> & { grey?: boolean };

export { ArticleQAIllustration } from './ArticleQAIllustration';
export { CrawlingIllustration } from './CrawlingIllustration';
export { EmptyStateIllustration } from './EmptyStateIllustration';
export { ListWebLinkIllustration } from './ListWebLinkIllustration';
export { NoPermissionIllustration } from './NoPermissionIllustration';
export { SuccessIllustration } from './SuccessIllustration';
export { SystemErrorIllustration } from './SystemErrorIllustration';
export { SystemMaintenanceIllustration } from './SystemMaintenanceIllustration';
