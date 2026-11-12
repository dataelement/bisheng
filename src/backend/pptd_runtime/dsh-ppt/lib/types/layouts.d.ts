/** Registered native layout catalog and deterministic routing. */
import type { OfficeDesignSpec, OfficeDraftSlide, OfficeLayoutHint, OfficeLayoutId, OfficeSlideRole } from './protocol.ts';
/** One bounded layout contract shared by planning, rendering, and QA. */
export interface OfficeLayoutDefinition {
    readonly id: OfficeLayoutId;
    readonly name: string;
    readonly roles: readonly OfficeSlideRole[];
    readonly description: string;
    readonly minBullets: number;
    readonly maxBullets: number;
    readonly maxTitleCharacters: number;
    readonly components: readonly string[];
}
/** The ten layouts supported by the first component-library release. */
export declare const OFFICE_LAYOUTS: readonly OfficeLayoutDefinition[];
/**
 * Look up one registered layout or fail closed.
 * @param id - Registered layout identity.
 * @returns Registered layout definition.
 */
export declare function layoutDefinition(id: OfficeLayoutId): OfficeLayoutDefinition;
/**
 * Test whether an input hint already names a registered layout.
 * @param value - Optional layout hint from a draft slide.
 * @returns Whether the hint is a registered layout identity.
 */
export declare function isRegisteredLayout(value: OfficeLayoutHint | undefined): value is OfficeLayoutId;
/**
 * Convert legacy coarse layouts to their nearest registered equivalent.
 * @param value - Registered or legacy coarse layout hint.
 * @returns Registered layout identity.
 */
export declare function legacyLayout(value: OfficeLayoutHint): OfficeLayoutId;
/**
 * Infer the narrative role from content before selecting a visual layout.
 * @param slide - Draft slide content and optional layout hint.
 * @param index - Zero-based position in the deck.
 * @param total - Total slide count.
 * @returns Inferred narrative role.
 */
export declare function inferSlideRole(slide: OfficeDraftSlide, index: number, total: number): OfficeSlideRole;
/**
 * Select a layout from role, evidence shape, and the deck-level design strategy.
 * @param slide - Draft slide content and optional requested layout.
 * @param role - Inferred narrative role.
 * @param design - Deck-level chart strategy.
 * @returns Selected registered layout, resolved role, source, and rationale.
 */
export declare function selectLayout(slide: OfficeDraftSlide, role: OfficeSlideRole, design: Pick<OfficeDesignSpec, 'chartStrategy'>): {
    readonly id: OfficeLayoutId;
    readonly role: OfficeSlideRole;
    readonly source: 'automatic' | 'requested' | 'legacy' | 'adapted';
    readonly rationale: string;
};