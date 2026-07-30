export function sumMetricValues(values: unknown): number {
  if (!Array.isArray(values)) {
    return 0
  }

  return values.reduce<number>((total, value) => {
    if (value === null || value === undefined || value === '') {
      return total
    }

    const numericValue = Number(value)
    return Number.isFinite(numericValue) ? total + numericValue : total
  }, 0)
}
