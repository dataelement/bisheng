import type {
  DimensionField,
  PivotColumnAliases,
} from "../../types/dataConfig"

interface ResolvePivotColumnLabelsOptions {
  columns: string[]
  stackDimension?: DimensionField
  aliasConfig?: PivotColumnAliases
}

export function resolvePivotColumnLabels({
  columns,
  stackDimension,
  aliasConfig,
}: ResolvePivotColumnLabelsOptions): string[] {
  if (
    !stackDimension
    || !aliasConfig
    || aliasConfig.fieldId !== stackDimension.fieldId
  ) {
    return columns
  }

  return columns.map(column => {
    const alias = aliasConfig.aliases[column]?.trim()
    return alias || column
  })
}
