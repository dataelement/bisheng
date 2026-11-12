/** Shared PPTD color normalization used by checking, preview, and PPTX export. */
type Dict = Record<string, unknown>;
interface PptdColorProject {
    readonly theme: Dict;
}
/** Deterministic series palette used when a chart series omits an explicit color. */
export declare const PPTD_CHART_SERIES_PALETTE: readonly ["#2563EB", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6", "#06B6D4"];
/** Resolve a literal or theme-referenced PPTD color without applying a silent fallback. */
export declare function resolvePptdColor(project: PptdColorProject, value: unknown): string | undefined;
/**
 * Normalize chart-series colors from either color scalars or solid paint objects.
 * Pie series may supply an array; unsupported paints and invalid colors return undefined.
 */
export declare function resolvePptdChartSeriesColors(project: PptdColorProject, value: unknown): readonly string[] | undefined;
export {};