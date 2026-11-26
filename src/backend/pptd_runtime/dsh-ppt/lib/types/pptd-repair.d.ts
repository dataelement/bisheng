/** Deterministic, explicitly requested PPTD source repairs for `check --level auto`. */
import { type PptdCheck } from './pptd.ts';
/** One source mutation made by the deterministic repair engine. */
export interface PptdRepairAction {
    readonly file: string;
    readonly elementId?: string;
    readonly kind: 'convert-type' | 'delete-optional-field' | 'delete-invalid-element';
    readonly field: string;
    readonly message: string;
}
/** Complete repair receipt returned after source files are rewritten and rechecked. */
export interface PptdRepairResult {
    readonly changedFiles: readonly string[];
    readonly actions: readonly PptdRepairAction[];
    readonly check: PptdCheck;
}
/** Apply bounded deterministic repairs to the selected source pages and recheck the project. */
export declare function repairPptdProject(inputPath: string, selectedPages?: ReadonlySet<number>): Promise<PptdRepairResult>;