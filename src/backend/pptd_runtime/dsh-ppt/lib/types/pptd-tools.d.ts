/** Model-facing tools for direct, inspectable PPTD project authoring. */
import type { Context } from '@deepseek-ai/cordis';
import type { PptService } from './ppt-service.ts';
/** Register the direct PPTD project workflow used by PPT mode. */
export declare function registerPptdProjectTools(ctx: Context, service: Pick<PptService, 'createPptdDeck'>): void;