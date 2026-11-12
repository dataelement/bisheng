/** Model-facing tools for the DSH PPTD workflow. */
import type { Context } from '@deepseek-ai/cordis';
import { type OfficePptState } from './protocol.ts';
import type { PptService } from './ppt-service.ts';
/** Stable host guidance for the single PPTD route. */
export declare const DSH_PPT_PROMPT: string;
/** Render authoritative composer state as model-only runtime context. */
export declare function pptComposerContext(state: OfficePptState): string | undefined;
/** Register the DSH presentation tools and session Skill injection. */
export declare function registerPptTools(ctx: Context, service: PptService): void;