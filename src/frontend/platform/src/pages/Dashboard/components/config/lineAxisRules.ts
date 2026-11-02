import { ChartType } from "../../types/dataConfig"
import { resolveMetricNumberFormat } from "./useChartState"

export type LineMetricKind = "number" | "percent" | "duration" | "storage"

export type LineMetricDecision =
  | { ok: true }
  | { ok: false, reason: "max" | "kind" }

interface LineMetricSource {
  isDivide?: string
  numberFormat?: { type?: string }
}

export function isSharedAxisLineChart(chartType: ChartType): boolean {
  return chartType === ChartType.Line || chartType === ChartType.StackedLine
}

export function maxSharedLineMetrics(chartType: ChartType): number {
  return chartType === ChartType.StackedLine ? 3 : 2
}

export function lineLimitToastKey(chartType: ChartType): string {
  return chartType === ChartType.StackedLine
    ? "componentConfigDrawer.toast.lineMaxThree"
    : "componentConfigDrawer.toast.lineMaxTwo"
}

export function maxCategoryDimensions(chartType: ChartType): number {
  return isSharedAxisLineChart(chartType) ? 1 : 2
}

export function lineMetricShareKind(metric: LineMetricSource): LineMetricKind {
  const formatType = resolveMetricNumberFormat(metric).type
  if (formatType === "percent" || formatType === "duration" || formatType === "storage") {
    return formatType
  }
  return "number"
}

function canShare(left: LineMetricKind, right: LineMetricKind): boolean {
  return (left === "number" && right === "number") || (left === "percent" && right === "percent")
}

function kindsCanShare(metrics: LineMetricSource[]): boolean {
  if (metrics.length === 0) return true
  const kinds = metrics.map(lineMetricShareKind)
  return kinds.every(kind => canShare(kinds[0], kind))
}

export function canAddLineMetric(
  existing: LineMetricSource[],
  incoming: LineMetricSource,
  maxLines = 2,
): LineMetricDecision {
  if (existing.length >= maxLines) return { ok: false, reason: "max" }
  if (existing.length === 0) return { ok: true }
  if (!kindsCanShare([...existing, incoming])) return { ok: false, reason: "kind" }
  return { ok: true }
}

export function canChangeLineMetricFormat(
  metrics: LineMetricSource[],
  index: number,
  nextFormat: LineMetricSource["numberFormat"],
): LineMetricDecision {
  if (metrics.length < 2 || index < 0 || index >= metrics.length) return { ok: true }
  const nextMetrics = metrics.map((metric, metricIndex) => (
    metricIndex === index ? { ...metric, numberFormat: nextFormat } : metric
  ))
  if (!kindsCanShare(nextMetrics)) return { ok: false, reason: "kind" }
  return { ok: true }
}
