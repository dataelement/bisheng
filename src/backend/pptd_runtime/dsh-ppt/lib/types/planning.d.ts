/** Narrative, visual, and page-layout planning for native presentations. */
import type { OfficeCreateInput, OfficeDesignSpec, OfficeDraftSlide, OfficeSlide, OfficeSlideId, OfficeSlidePlan, OfficeStorySpec, OfficeTemplate } from './protocol.ts';
interface PlanningSlide extends OfficeDraftSlide {
    readonly id: OfficeSlideId;
}
/** Complete deterministic planning result consumed by the renderer. */
export interface OfficePlanningArtifacts {
    readonly story: OfficeStorySpec;
    readonly design: OfficeDesignSpec;
    readonly slides: readonly OfficeSlide[];
    readonly plan: readonly OfficeSlidePlan[];
}
/**
 * Build the deck-wide visual contract before selecting any page layout.
 * @param template - Selected theme and extracted design facts.
 * @param slides - Draft slide content used for density inference.
 * @param requested - Optional user or model design preferences.
 * @returns Deck-wide visual contract.
 */
export declare function buildDesignSpec(template: OfficeTemplate, slides: readonly PlanningSlide[], requested: OfficeCreateInput['design'] | undefined): OfficeDesignSpec;
/**
 * Plan story, design, and registered layouts as independently inspectable artifacts.
 * @param input - Presentation intent, template, content, and optional design preferences.
 * @returns Planned story, design, slide models, and page layouts.
 */
export declare function planPresentation(input: {
    readonly title: string;
    readonly template: OfficeTemplate;
    readonly slides: readonly PlanningSlide[];
    readonly audience?: string;
    readonly purpose?: OfficeStorySpec['purpose'];
    readonly objective?: string;
    readonly design?: OfficeCreateInput['design'];
}): OfficePlanningArtifacts;
export {};