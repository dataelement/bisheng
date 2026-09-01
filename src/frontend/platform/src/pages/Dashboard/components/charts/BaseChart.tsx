"use client"

import { ChartType, ComponentConfig, ComponentStyleConfig } from '@/pages/Dashboard/types/dataConfig'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { colorSchemes, convertToEChartsTheme } from '../../colorSchemes'
import { ChartDataResponse, PieDataItem } from '../../types/chartData'
import { useComponentExport } from '../export/useComponentExport'
import { unitConversion } from './MetricCard'
import { applyPieResultLimit } from './pieChartData'

// Dynamic loading of ECharts.
const loadECharts = async () => {
  if ((window as any).echarts) {
    return (window as any).echarts
  }

  const script = document.createElement('script')
  script.src = `${__APP_ENV__?.BASE_URL || ''}/echarts.min.js`
  script.type = 'module'

  return new Promise((resolve, reject) => {
    script.onload = () => {
      const checkECharts = setInterval(() => {
        if ((window as any).echarts) {
          clearInterval(checkECharts)
          resolve((window as any).echarts)
        }
      }, 100)
    }
    script.onerror = reject
    document.head.appendChild(script)
  })
}

interface BaseChartProps {
  data: ChartDataResponse
  chartType: ChartType
  isDark: boolean
  dataConfig?: ComponentConfig // Chart component configuration.
  styleConfig: ComponentStyleConfig
  // F058 AC-09: optional — omit (e.g. unsaved draft component) to disable
  // click-a-category-to-export-its-detail.
  dashboardId?: string
  componentId?: string
}

type AxisLabelTooltip = {
  text: string
  x: number
  y: number
  alignRight: boolean
  alignBottom: boolean
}

const CATEGORY_LABEL_MAX_LENGTH = 10

export const formatCategoryAxisLabel = (value: unknown) => {
  if (!value) return ''

  return String(value)
    .split('\n')
    .map(line => line.length > CATEGORY_LABEL_MAX_LENGTH
      ? `${line.slice(0, CATEGORY_LABEL_MAX_LENGTH)}...`
      : line)
    .join('\n')
}

export const getTruncatedAxisLabelText = (params: any) => {
  const isAxisLabel = (params?.componentType === 'xAxis' || params?.componentType === 'yAxis')
    && params?.targetType === 'axisLabel'
  if (!isAxisLabel) return null

  const text = String(params.value ?? '')
  return formatCategoryAxisLabel(text) === text ? null : text
}

export function BaseChart({ isDark, data, chartType, dataConfig, styleConfig, dashboardId, componentId }: BaseChartProps) {
  const { t } = useTranslation("dashboard")

  // F058 AC-09: click a chart category (bar segment, pie slice, ...) to export that
  // category's detail rows. dataConfig.dimensions[0] is the chart's category axis.
  const { exportDetail } = useComponentExport({
    dashboardId: dashboardId || "",
    componentId: componentId || "",
  })

  const chartRef = useRef<any>(null)
  const domRef = useRef<HTMLDivElement>(null)
  const echartsLibRef = useRef(null)
  const [isLoading, setIsLoading] = useState(true)
  const [axisLabelTooltip, setAxisLabelTooltip] = useState<AxisLabelTooltip | null>(null)

  // load ECharts
  useEffect(() => {
    loadECharts()
      .then((echarts) => {
        echartsLibRef.current = echarts
        setIsLoading(false)
      })
      .catch((err) => {
        console.error('Failed to load ECharts:', err)
        setIsLoading(false)
      })
  }, [])

  const renderChart = () => {
    if (!chartRef.current || !domRef.current) return;

    const containerSize = [domRef.current.clientWidth || 0, domRef.current.clientHeight || 0];

    const option = generateChartOption({
      data,
      chartType,
      dataConfig,
      styleConfig,
      containerSize,
      otherLabel: t("componentConfigDrawer.otherResults", { defaultValue: "其他" }),
    });

    chartRef.current.setOption(option);
    chartRef.current.resize();
  }
  // Initialize and update the chart.
  const [screenFull, setScreenFull] = useState(false)
  useEffect(() => {
    if (!echartsLibRef.current || !domRef.current || isLoading) return

    // clear
    if (chartRef.current) {
      chartRef.current.dispose()
      chartRef.current = null
    }

    try {
      // theme
      const theme = styleConfig.themeColor || 'professional-blue'
      const activeScheme = colorSchemes.find(s => s.id === theme);
      const themeName = `${activeScheme.id}${isDark ? '-dark' : ''}`;
      const themeConfig = convertToEChartsTheme(activeScheme, isDark ? 'dark' : 'light');
      // register Theme
      echartsLibRef.current.registerTheme(themeName, themeConfig);
      // init echarts
      chartRef.current = echartsLibRef.current.init(domRef.current, themeName)

      const handleAxisLabelMouseOver = (params: any) => {
        const text = getTruncatedAxisLabelText(params)
        if (!text || !domRef.current) {
          setAxisLabelTooltip(null)
          return
        }

        const pointerEvent = params.event?.event ?? params.event
        const x = pointerEvent?.offsetX ?? pointerEvent?.zrX ?? 0
        const y = pointerEvent?.offsetY ?? pointerEvent?.zrY ?? 0
        setAxisLabelTooltip({
          text,
          x,
          y,
          alignRight: x > domRef.current.clientWidth / 2,
          alignBottom: y > domRef.current.clientHeight / 2,
        })
      }
      const handleAxisLabelMouseOut = () => setAxisLabelTooltip(null)

      chartRef.current.on('mouseover', handleAxisLabelMouseOver)
      chartRef.current.on('mouseout', handleAxisLabelMouseOut)

      // F058 AC-09: click-to-export-detail, only for chart types with a real category
      // axis / pie slice (a metric card or a bare line-with-no-dimension has nothing
      // meaningful to drill into).
      const categoryDimensionField = dataConfig?.dimensions?.[0]?.fieldId
      if (dashboardId && componentId && categoryDimensionField) {
        chartRef.current.on('click', (params: any) => {
          const categoryValue = params?.name
          if (categoryValue === undefined || categoryValue === null || categoryValue === '') return
          void exportDetail(categoryDimensionField, categoryValue)
        })
      }

      renderChart();
    } catch (err) {
      console.error('Failed to initialize chart:', err)
    }

    return () => {
      if (chartRef.current) {
        chartRef.current.dispose()
        chartRef.current = null
      }
    }
  }, [screenFull, echartsLibRef.current, data, chartType, dataConfig, styleConfig, isLoading, isDark])

  // resize
  useEffect(() => {
    if (!chartRef.current || !domRef.current) return;

    const handleResize = () => {
      renderChart();
    };

    const resizeObserver = new ResizeObserver(() => {
      handleResize()
    })

    resizeObserver.observe(domRef.current)
    window.addEventListener('resize', handleResize)

    return () => {
      resizeObserver.disconnect()
      window.removeEventListener('resize', handleResize)
    }
  }, [chartRef.current])

  // screen full
  useEffect(() => {
    const handleFullscreenChange = () => {
      setScreenFull(!screenFull)
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    document.addEventListener('webkitfullscreenchange', handleFullscreenChange);

    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      document.removeEventListener('webkitfullscreenchange', handleFullscreenChange);
    };
  }, []);

  if (isLoading) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="text-sm text-muted-foreground">{t('updatingCharts')}...</div>
      </div>
    )
  }

  return (
    <div className="relative size-full">
      <div ref={domRef} className="size-full" />
      {axisLabelTooltip && (
        <div
          className="pointer-events-none absolute z-10 max-w-[320px] whitespace-pre-wrap break-words rounded bg-white px-3 py-2 text-xs text-gray-700 shadow-lg ring-1 ring-black/10 dark:bg-gray-800 dark:text-gray-100"
          style={{
            left: axisLabelTooltip.x + (axisLabelTooltip.alignRight ? -12 : 12),
            top: axisLabelTooltip.y + (axisLabelTooltip.alignBottom ? -12 : 12),
            transform: `translate(${axisLabelTooltip.alignRight ? '-100%' : '0'}, ${axisLabelTooltip.alignBottom ? '-100%' : '0'})`,
          }}
        >
          {axisLabelTooltip.text}
        </div>
      )}
    </div>
  )
}


/**
 * Generate ECharts configuration based on chart type and data.
 */
export function generateChartOption(props: {
  data: ChartDataResponse;
  chartType: ChartType;
  dataConfig?: ComponentConfig;
  styleConfig: ComponentStyleConfig;
  containerSize?: number[];
  otherLabel?: string;
}): any {
  const { chartType } = props;

  // 根据图表类型分发到不同的构建器
  if (chartType === 'pie' || chartType === 'donut') {
    return getPieChartOption(
      props.data,
      chartType,
      props.styleConfig,
      props.dataConfig,
      props.otherLabel,
    );
  }

  return getCartesianChartOption(props.data, chartType, props.styleConfig, props.dataConfig, props.containerSize);
}



const getPieChartOption = (
  data: ChartDataResponse,
  chartType: ChartType,
  styleConfig: ComponentStyleConfig,
  dataConfig?: ComponentConfig,
  otherLabel = "其他",
) => {
  const { series } = data;
  const isDonut = chartType === 'donut';
  const metricNumberFormat = dataConfig && 'metrics' in dataConfig
    ? dataConfig.metrics[0]?.numberFormat
    : undefined;
  const isPercentMetric = metricNumberFormat?.type === 'percent';

  const formatMetricValue = (value: unknown) => {
    if (!metricNumberFormat) return String(value);
    const [formattedValue, unit] = unitConversion(value, dataConfig);
    return `${formattedValue}${unit}`;
  };

  const tooltipFormatter = (params: any) => {
    const name = params.name.replaceAll('\n', '<br/>');
    const formattedValue = formatMetricValue(params.value);
    return isPercentMetric
      ? `${name}: ${formattedValue}`
      : `${name}: ${formattedValue} (${params.percent}%)`;
  };

  const dataLabelFormatter = isPercentMetric
    ? (params: any) => `${params.name}: ${formatMetricValue(params.value)}`
    : '{b}: {d}%';

  return {
    backgroundColor: styleConfig.bgColor,
    // title: buildTitleOption(styleConfig),
    legend: buildLegendOption(styleConfig),
    tooltip: buildTooltipOption('item', tooltipFormatter),
    series: series.map((s) => ({
      name: s.name,
      left: styleConfig.legendPosition === 'left' && 100,
      right: styleConfig.legendPosition === 'right' && 100,
      bottom: styleConfig.legendPosition === 'bottom' && 20,
      top: styleConfig.legendPosition === 'top' && 20,
      type: 'pie',
      radius: isDonut ? ['40%', '70%'] : '70%',
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 0, borderColor: '#fff', borderWidth: 2 },
      label: {
        show: styleConfig.showDataLabel ?? true,
        formatter: dataLabelFormatter,
        fontSize: 10,
        color: "#666",
        textBorderWidth: 0,
        textBorderColor: 'none',
        textShadowBlur: 0,
        textShadowColor: 'none',
      },
      labelLine: {
        show: styleConfig.showDataLabel ?? true,
        length: 12,
        length2: 10,
      },
      labelLayout: {
        hideOverlap: true,
        moveOverlap: 'shiftY',
      },
      emphasis: {
        label: {
          show: styleConfig.showDataLabel ?? true,
          fontSize: 10,
          fontWeight: 'normal',
        },
      },
      data: applyPieResultLimit(s.data as PieDataItem[], dataConfig?.resultLimit, otherLabel),
    })),
  };
};


const getCartesianChartOption = (
  data: ChartDataResponse,
  chartType: ChartType,
  styleConfig: ComponentStyleConfig,
  dataConfig?: ComponentConfig,
  containerSize: number[] = []
) => {
  const { dimensions, series } = data;
  const isHorizontal = chartType.includes('horizontal');
  const isStacked = chartType.includes('stacked');
  const isLineOrArea = chartType.includes('line') || chartType.includes('area');
  const isArea = chartType.includes('area')

  // aixs title tyle
  const [containerWidth = 500, containerHeight = 500] = containerSize
  const axisWidth = containerWidth - styleConfig.xAxisTitle.length * styleConfig.xAxisFontSize - 60;
  const axisHeight = containerHeight - styleConfig.yAxisTitle.length * styleConfig.yAxisFontSize - 60;

  // Tooltip
  const tooltipFormatter = (params: any[]) => {
    const originName = params[0]?.name || '';
    const shortName = originName.replace(/(.{50})/g, '$1<br/>');
    let res = shortName.replaceAll('\n', '<br/>') + '<br/>';
    params.forEach((item) => {
      res += item.value === undefined ? '' : `${item.marker} ${item.seriesName}: <b>${unitConversion(item.value, dataConfig).join('')}</b><br/>`;
    });
    return res;
  };

  //  Axis
  const xAxisTitleStyle = getTextStyle({
    fontSize: styleConfig.xAxisFontSize,
    color: styleConfig.xAxisColor,
    bold: styleConfig.xAxisBold,
    italic: styleConfig.xAxisItalic
  });
  const yAxisTitleStyle = getTextStyle({
    fontSize: styleConfig.yAxisFontSize,
    color: styleConfig.yAxisColor,
    bold: styleConfig.yAxisBold,
    italic: styleConfig.yAxisItalic
  });

  // (Category Axis)
  const categoryAxis = {
    type: 'category',
    data: dimensions,
    triggerEvent: true,
    axisLabel: {
      show: styleConfig.showAxis ?? true,
      rotate: 0,
      interval: 'auto',
      formatter: formatCategoryAxisLabel,
      hideOverlap: true,
      color: '#666'
      // interval: 0,
      // hideOverlap: true,
      // overflow: 'break'
      // ...axisLabelStyle,
    },
    name: styleConfig.xAxisTitle || '',
    nameLocation: 'center',
    nameTextStyle: {
      ...xAxisTitleStyle,
      padding: [0, 0, 0, styleConfig.xAxisAlign === 'right' ? axisWidth : styleConfig.xAxisAlign === 'left' ? -axisWidth : 0]
    },
    inverse: isHorizontal
  };

  // (Value Axis)
  const valueAxis = {
    type: 'value',
    axisLabel: {
      show: styleConfig.showAxis ?? true,
      formatter: (val: any) => unitConversion(val, dataConfig).join(''),
      color: '#666'
    },
    splitLine: { show: styleConfig.showGrid ?? true },
    name: styleConfig.yAxisTitle || '',
    nameLocation: 'center',
    nameRotate: isHorizontal ? 0 : 90,
    nameTextStyle: {
      ...yAxisTitleStyle,
      padding: [0, 0, 0, styleConfig.yAxisAlign === 'right' ? axisHeight : styleConfig.yAxisAlign === 'left' ? -axisHeight : 0]
    },
    boundaryGap: [0, '20%'],
  };

  const lastValueIndexes = dimensions.map((_, dimIdx) => {
    let lastIdx = -1;
    for (let sIdx = series.length - 1; sIdx >= 0; sIdx--) {
      const val = series[sIdx].data[dimIdx];
      // 只有当值存在且大于 0 时，才认为是这一列的“顶端”
      if (val !== null && val !== undefined && val > 0) {
        lastIdx = sIdx;
        break;
      }
    }
    return lastIdx;
  });
  // Series
  const cartesianSeries = series.map((s, index) => {
    const processedData = s.data.map((val, dimIdx) => {
      const isTopItem = lastValueIndexes[dimIdx] === index;

      // 如果是顶端项，则单独给该 data item 设置样式
      if (!isLineOrArea && isStacked && isTopItem) {
        return {
          value: val,
          itemStyle: {
            borderRadius: isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]
          }
        };
      }
      return val;
    });

    const item: any = {
      name: s.name,
      data: processedData,
      type: isLineOrArea ? 'line' : 'bar',
      symbol: 'circle',
      symbolSize: 0,
      itemStyle: {
        borderRadius: (!isLineOrArea && !isStacked)
          ? (isHorizontal ? [0, 4, 4, 0] : [4, 4, 0, 0])
          : 0
      }
    };

    if (styleConfig.showDataLabel) {
      item.label = {
        show: true,
        // F058 AC-05: all horizontal-orientation bar types (not just the grouped
        // variant) must show the value at the bar's end, not the vertical 'top'
        // position (which reads as "middle of the bar" when the axis is horizontal).
        position: isHorizontal ? 'right' : 'top',
        fontSize: 10,
        color: "#666",
        formatter: (params: any) => unitConversion(params.value, dataConfig).join('')
      };
      item.labelLayout = {
        hideOverlap: true
      }
    }
    if (isStacked) item.stack = 'total';
    if (isArea) item.areaStyle = { opacity: 0.1 };
    // if (isLineOrArea) item.smooth = true;

    return item;
  });

  let grid = {
    left: 0,
    right: 0,
    top: 0,
    bottom: 0,
    // containLabel: true,
  }
  if (styleConfig.showLegend) {
    const titleBottom = (styleConfig.xAxisTitle ? 18 : 0) + ((dataConfig.dimensions.length - 1) * 10);
    const bottom = (styleConfig.legendPosition === 'bottom' ? 44 : 0) + titleBottom;
    grid = {
      left: styleConfig.legendPosition === 'left' ? 160 : 0,
      right: styleConfig.legendPosition === 'right' ? 100 : 0,
      top: styleConfig.legendPosition === 'top' ? 40 : 0,
      bottom,
    }
  }

  return {
    backgroundColor: styleConfig.bgColor,
    // title: buildTitleOption(styleConfig),
    legend: buildLegendOption(styleConfig, series.map(s => s.name)),
    tooltip: buildTooltipOption('axis', tooltipFormatter),
    grid,
    xAxis: isHorizontal ? valueAxis : categoryAxis,
    yAxis: isHorizontal ? categoryAxis : valueAxis,
    series: cartesianSeries,
  };
};

const getTextStyle = (config: {
  fontSize?: number; bold?: boolean; italic?: boolean; color?: string;
}) => {
  const style: any = {};
  if (config.fontSize !== undefined) style.fontSize = config.fontSize;
  if (config.bold) style.fontWeight = 'bold'; // ECharts use fontWeight, not fontStyle for bold
  if (config.italic) style.fontStyle = 'italic';
  if (config.color) style.color = config.color;
  return style;
};

/**
 * gen (Legend)
 */
const buildLegendOption = (styleConfig: ComponentStyleConfig, seriesNames?: string[]) => {
  if (styleConfig.showLegend === false) return undefined;

  const pos = styleConfig.legendPosition || 'top';
  const align = styleConfig.legendAlign || 'auto';
  const isVertical = pos === 'left' || pos === 'right';
  // computed
  const orient = isVertical ? 'vertical' : 'horizontal';
  const top = !isVertical
    ? (pos === 'top' ? 0 : 'auto')
    : (align === 'left' ? 0 : (align === 'right' ? 'auto' : 'center'));
  const bottom = !isVertical
    ? (pos === 'bottom' ? 0 : 'auto')
    : (align === 'right' ? 0 : 'auto');
  const left = isVertical
    ? (pos === 'left' ? 0 : 'auto')
    : (align === 'left' ? 0 : (align === 'right' ? 'auto' : 'center'));
  const right = isVertical
    ? (pos === 'right' ? 0 : 'auto')
    : (align === 'right' ? 0 : 'auto');

  return {
    data: seriesNames, // Pie chart doesn't strictly need this, but Cartesian does
    orient, top, bottom, left, right,
    textStyle: getTextStyle({
      fontSize: styleConfig.legendFontSize,
      bold: styleConfig.legendBold,
      italic: styleConfig.legendItalic,
      color: styleConfig.legendColor,
    }),
    type: 'scroll',
    itemHeight: 6,
    itemWidth: 6,
    icon: 'circle',
    itemStyle: {
      borderWidth: 0,
    },
  };
};

/**
 * geb Tooltip
 */
const buildTooltipOption = (type: 'axis' | 'item', formatter: (params: any) => string) => {
  return {
    trigger: type,
    confine: true,
    axisPointer: type === 'axis' ? { type: 'shadow' } : undefined,
    enterable: true,
    extraCssText: 'max-height: 500px; overflow-y: auto;',
    appendToBody: !document.fullscreenElement,
    // renderMode: 'html',
    formatter
  };
};
