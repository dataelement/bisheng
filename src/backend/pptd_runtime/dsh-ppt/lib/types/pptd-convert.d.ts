/** Bounded PPTX to PPTD v2 conversion used by the local CLI. */
import type { PptdProjectSource } from './pptd.ts';
/** One explicit fidelity boundary encountered while converting PPTX to PPTD. */
export interface PptxToPptdDiagnostic {
    readonly level: 'normalized' | 'placeholder' | 'unsupported';
    readonly slide?: number;
    readonly nodeId?: string;
    readonly elementId?: string;
    readonly bounds?: readonly [number, number, number, number];
    readonly feature: string;
    readonly message: string;
}
/** Conversion result and evidence returned before anything is written to disk. */
export interface PptxToPptdResult {
    readonly source: PptdProjectSource;
    readonly slideCount: number;
    readonly sourceNodeCount: number;
    readonly outputElementCount: number;
    readonly extractedAssetCount: number;
    readonly diagnostics: readonly PptxToPptdDiagnostic[];
}
/** Convert one bounded PPTX package into an editable, self-contained PPTD v2 project. */
export declare function convertPptxToPptd(bytes: Uint8Array, fileName: string, options?: {signal?: AbortSignal}): Promise<PptxToPptdResult>;
