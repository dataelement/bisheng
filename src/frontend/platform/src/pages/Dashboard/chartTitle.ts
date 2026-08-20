export const CHART_TITLE_MAX_LENGTH = 30

export const limitChartTitleLength = (value: string) => (
  value.slice(0, CHART_TITLE_MAX_LENGTH)
)
