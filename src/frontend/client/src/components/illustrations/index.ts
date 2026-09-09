/**
 * Re-export shim — the illustrations themselves now live in `@bisheng/ui`
 * (`packages/ui/src/components/Illustration/`), so both apps draw the same
 * artwork from one place. Call sites keep importing `~/components/illustrations`.
 *
 * KnowledgeSpaceIcon stays here on purpose: it swaps two bespoke drawings based
 * on the Recoil brand theme, and the library contract forbids state managers.
 * It is also not an --illus-* illustration (no palette, no grey draft).
 */
export {
  ArticleQAIllustration,
  CrawlingIllustration,
  EmptyStateIllustration,
  ListWebLinkIllustration,
  NoPermissionIllustration,
  SuccessIllustration,
  SystemErrorIllustration,
  SystemMaintenanceIllustration,
} from '@bisheng/ui';
export type { IllustrationProps } from '@bisheng/ui';

export { KnowledgeSpaceIcon } from './KnowledgeSpaceIcon';
