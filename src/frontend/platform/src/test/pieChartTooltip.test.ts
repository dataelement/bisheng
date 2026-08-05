import { describe, expect, it } from "vitest"
import { generateChartOption } from "../pages/Dashboard/components/charts/BaseChart"
import {
  ChartType,
  ComponentStyleConfig,
  DataConfig,
} from "../pages/Dashboard/types/dataConfig"

describe("pie chart tooltip", () => {
  it("formats a divide metric as a percentage without showing the slice share", () => {
    const dataConfig: DataConfig = {
      dimensions: [],
      metrics: [
        {
          fieldId: "participation_rate",
          fieldName: "全员参与占比",
          fieldCode: "participation_rate",
          isVirtual: true,
          sort: null,
          numberFormat: {
            type: "percent",
            decimalPlaces: 2,
            thousandSeparator: false,
          },
        },
      ],
      fieldOrder: [],
      filters: [],
      resultLimit: { limitType: "all" },
      isConfigured: true,
    }
    const option = generateChartOption({
      data: {
        dimensions: [],
        series: [
          {
            name: "",
            data: [
              {
                name: "2026-08-03 ~ 2026-08-09",
                value: 0.00023038820412394885,
              },
            ],
          },
        ],
      },
      chartType: ChartType.Pie,
      dataConfig,
      styleConfig: {} as ComponentStyleConfig,
    })

    expect(
      option.tooltip.formatter({
        name: "2026-08-03 ~ 2026-08-09",
        value: 0.00023038820412394885,
        percent: 100,
      }),
    ).toBe("2026-08-03 ~ 2026-08-09: 0.02%")
    expect(
      option.series[0].label.formatter({
        name: "2026-08-03 ~ 2026-08-09",
        value: 0.00023038820412394885,
      }),
    ).toBe("2026-08-03 ~ 2026-08-09: 0.02%")
  })
})
