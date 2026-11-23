/** Deterministic text-box capacity estimates shared by template references and PPT renderers. */
/** Inputs needed to estimate PowerPoint text wrapping in point coordinates. */
export interface TextLayoutInput {
    readonly text: string;
    readonly width: number;
    readonly height: number;
    readonly fontSize: number;
    readonly lineHeight?: number;
    readonly letterSpacing?: number;
    readonly bold?: boolean;
    readonly wrap?: boolean;
}
/** Deterministic text layout estimate used before native PowerPoint rendering. */
export interface TextLayoutMeasurement {
    readonly lineCount: number;
    readonly maxLineCount: number;
    readonly requiredHeight: number;
    readonly availableLineWidth: number;
    readonly widestLine: number;
    readonly horizontalOverflow: boolean;
    readonly overflow: boolean;
}
/**
 * Estimate native text wrapping while retaining the authored font size.
 * @param input - Text, box geometry, and effective text style in PowerPoint points.
 * @returns Estimated line use and overflow state.
 */
export declare function measureTextLayout(input: TextLayoutInput): TextLayoutMeasurement;
/**
 * Derive a conservative full-width character budget for an empty text region.
 * @param width - Text-region width in PowerPoint points.
 * @param height - Text-region height in PowerPoint points.
 * @param fontSize - Intended font size in points.
 * @param lineHeight - Line-height multiplier.
 * @returns Recommended full-width character count.
 */
export declare function recommendedTextCapacity(width: number, height: number, fontSize: number, lineHeight?: number): number;