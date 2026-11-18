/** Template-page visual relationships shared by extraction, persisted-state migration, and model references. */
import type { OfficeSlideRole, OfficeTemplate, OfficeTemplatePageRelationship } from './protocol.ts';
/** Infer the output content relationship when an older caller supplied only a slide role. */
export declare function contentRelationshipForRole(role: OfficeSlideRole | undefined): OfficeTemplatePageRelationship;
/** Check that the page's visual relationship can express the authored content relationship. */
export declare function templateRelationshipSupportsContent(source: OfficeTemplatePageRelationship, content: OfficeTemplatePageRelationship): boolean;
/**
 * Apply current relational template semantics to built-in and persisted custom templates.
 * @param template - Template whose indexed source pages require visual enrichment.
 * @returns The template with relational page semantics populated.
 */
export declare function enrichTemplateVisualSemantics(template: OfficeTemplate): OfficeTemplate;