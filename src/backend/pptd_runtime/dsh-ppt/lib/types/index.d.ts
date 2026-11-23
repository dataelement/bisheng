/** Host entry for the installable DSH PPT bundle. */
import type { Context } from '@deepseek-ai/cordis';
import z from '@deepseek-ai/schemastery';
/** Cordis plugin identity. */
export declare const name = "dsh-ppt";
/** Required host services. */
export declare const inject: string[];
/** Local storage and PPT rendering ceilings. */
export interface Config {
    /** Absolute local root for state, revisions, and audit. */
    root: string;
    /** Maximum slides accepted in one generated presentation. */
    maxSlides?: number;
    /** Maximum persisted presentations in one DSH session. */
    maxDecksPerSession?: number;
    /** Maximum recent activity records retained in session state. */
    maxActivities?: number;
    /** Absolute DSH PPT Skill override. The package-bundled Skill is the default. */
    pptSkillRoot?: string;
}
/** Loader schema with conservative local defaults. */
export declare const Config: z<Config>;
/** Compose storage, browser RPC, and bounded model tools. */
export declare function apply(ctx: Context, config: Config): Promise<void>;
export type { PptService } from './ppt-service.ts';