/** Truth-preserving numeric evidence parsing shared by planning, rendering, and QA. */
export interface OfficeNumericDatum {
    readonly label: string;
    readonly value: number;
    readonly unit: string;
}
/** Same-unit numeric series that can be rendered without changing source meaning. */
export interface OfficeChartSeries {
    readonly labels: readonly string[];
    readonly values: readonly number[];
    readonly unit: string;
}
/**
 * Parse the final numeric claim from one content item without inventing a value.
 * @param item - Source content item that may contain a numeric claim.
 * @returns Parsed datum, or null when the item carries no usable numeric claim.
 */
export declare function numericDatum(item: string): OfficeNumericDatum | null;
/**
 * Count all explicit numeric claims, including KPI values with different units.
 * @param items - Ordered source content items.
 * @returns Number of items carrying a usable numeric claim.
 */
export declare function numericEvidenceCount(items: readonly string[]): number;
/**
 * Build a complete same-unit series in source order.
 * Mixed-unit or nonnumeric KPI facts remain valid content but never disappear into a partial chart.
 * @param items - Ordered source content items.
 * @returns A complete same-unit series, or an empty series when a faithful chart is unavailable.
 */
export declare function chartSeries(items: readonly string[]): OfficeChartSeries;