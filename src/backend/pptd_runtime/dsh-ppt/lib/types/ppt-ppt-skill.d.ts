/** First-party DSH PPT workflow Skill bundled with the local PPTD route. */
import type { Context } from '@deepseek-ai/cordis';
/** Stable Skill name shown in the task trajectory for the DSH PPT route. */
export declare const DSH_PPT_SKILL_NAME = "dsh-ppt";
/** Register the DSH PPT Skill shipped in this package. */
export declare function registerPptSkill(ctx: Context, skillRoot: string): void;