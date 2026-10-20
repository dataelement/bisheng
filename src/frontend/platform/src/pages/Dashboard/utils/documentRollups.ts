export interface DocumentRollup {
  metric_index: number
  dimension_indexes: number[]
  rows: { dimensions: unknown[]; value: number }[]
}

export function dimensionValueKey(values: unknown[]): string {
  return JSON.stringify(values.map(value => value == null ? null : String(value)))
}

export function documentRollupLookup(rollups?: DocumentRollup[]) {
  const selected = rollups?.filter(item => item.metric_index === 0)
  if (!selected?.length) return undefined
  const groups = new Map(selected.map(item => [
    JSON.stringify(item.dimension_indexes),
    new Map(item.rows.map(row => [
      dimensionValueKey(row.dimensions), row.value,
    ])),
  ]))
  return (indexes: number[], values: unknown[]): number => {
    const group = groups.get(JSON.stringify(indexes))
    if (!group) throw new Error("文档统计缺少服务端合计，请刷新后重试")
    return group.get(dimensionValueKey(values)) ?? 0
  }
}
