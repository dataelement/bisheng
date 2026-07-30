import { ResultLimitType } from "../../types/dataConfig"
import { PieDataItem } from "../../types/chartData"

export interface PieChartResultLimit {
  limitType: ResultLimitType
  limit?: number
}

export function applyPieResultLimit(
  data: PieDataItem[],
  resultLimit?: PieChartResultLimit,
  otherLabel = "其他",
): PieDataItem[] {
  if (!resultLimit || resultLimit.limitType === "all") {
    return data
  }

  const limit = Math.max(1, Math.floor(Number(resultLimit.limit) || 1))
  const topData = data.slice(0, limit)

  if (resultLimit.limitType !== "limited_with_other") {
    return topData
  }

  const remainingData = data.slice(limit)
  if (remainingData.length === 0) {
    return topData
  }

  const otherValue = remainingData.reduce((sum, item) => {
    const value = Number(item.value)
    return Number.isFinite(value) ? sum + value : sum
  }, 0)

  return [
    ...topData,
    {
      name: otherLabel,
      value: otherValue,
    },
  ]
}
