"use client"

import { ChartType, ComponentConfig, ComponentStyleConfig } from '@/pages/Dashboard/types/dataConfig'
import { useEffect, useRef, useState } from 'react'
import { colorSchemes, convertToEChartsTheme } from '../../colorSchemes'
import { ChartDataResponse } from '../../types/chartData'
import { unitConversion } from './MetricCard'
import { useTranslation } from 'react-i18next'

// Dynamic loading of ECharts.
const loadECharts = async () => {
  if ((window as any).echarts) {
    return (window as any).echarts
  }

  const script = document.createElement('script')
  script.src = `${(window as any).__APP_ENV__?.BASE_URL || ''}/echarts.min.js`
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
}

export function BaseChart({ isDark, data, chartType, dataConfig, styleConfig }: BaseChartProps) {
  const { t } = useTranslation("dashboard")

  const chartRef = useRef<any>(null)
  const domRef = useRef<HTMLDivElement>(null)
  const echartsLibRef = useRef(null)
  const [isLoading, setIsLoading] = useState(true)

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

  // Initialize and update the chart.
  useEffect(() => {
    if (!echartsLibRef.current || !domRef.current || isLoading) return

    // clear
    if (chartRef.current) {
      chartRef.current.dispose()
      chartRef.current = null
    }

    console.log('render echarts :>> ');

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
      const option = generateChartOption({ data, chartType, dataConfig, styleConfig })
      chartRef.current.setOption(option, true)
    } catch (err) {
      console.error('Failed to initialize chart:', err)
    }

    return () => {
      if (chartRef.current) {
        chartRef.current.dispose()
        chartRef.current = null
      }
    }
  }, [echartsLibRef.current, data, chartType, dataConfig, styleConfig, isLoading, isDark])

  // resize
  useEffect(() => {
    if (!chartRef.current) return

    const resizeObserver = new ResizeObserver(() => {
      chartRef.current?.resize()
    })

    if (domRef.current) {
      resizeObserver.observe(domRef.current)
    }

    const handleResize = () => {
      chartRef.current?.resize()
    }
    window.addEventListener('resize', handleResize)

    return () => {
      resizeObserver.disconnect()
      window.removeEventListener('resize', handleResize)
    }
  }, [chartRef.current])

  if (isLoading) {
    return (
      <div className="w-full h-full flex items-center justify-center">
        <div className="text-sm text-muted-foreground">{t('updatingCharts')}...</div>
      </div>
    )
  }

  return <div ref={domRef} style={{ width: '100%', height: `100%` }} />
}


/**
 * Generate ECharts configuration based on chart type and data.
 */
export function generateChartOption(props: {
  data: ChartDataResponse;
  chartType: ChartType;
  dataConfig?: ComponentConfig;
  styleConfig: ComponentStyleConfig;
}): any {
  const { chartType } = props;

  // 根据图表类型分发到不同的构建器
  if (chartType === 'pie' || chartType === 'donut') {
    return getPieChartOption(props.data, chartType, props.styleConfig);
  }

  return getCartesianChartOption(props.data, chartType, props.styleConfig, props.dataConfig);
}



const getPieChartOption = (
  data: ChartDataResponse,
  chartType: ChartType,
  styleConfig: ComponentStyleConfig
) => {
  const { series } = data;
  const isDonut = chartType === 'donut';

  const tooltipFormatter = (params: any) => {
    return `${params.name.replaceAll('\n', '<br/>')}: ${params.value} (${params.percent}%)`;
  };

  return {
    backgroundColor: styleConfig.bgColor,
    // title: buildTitleOption(styleConfig),
    legend: buildLegendOption(styleConfig),
    tooltip: buildTooltipOption('item', tooltipFormatter),
    series: series.map((s) => ({
      name: s.name,
      left: styleConfig.legendPosition === 'left' && 100,
      right: styleConfig.legendPosition === 'right' && 100,
      bottom: styleConfig.legendPosition === 'bottom' && 40,
      type: 'pie',
      radius: isDonut ? ['40%', '70%'] : '70%',
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 0, borderColor: '#fff', borderWidth: 2 },
      label: {
        show: styleConfig.showDataLabel ?? true,
        formatter: '{b}: {d}%',
      },
      emphasis: {
        label: { show: true, fontSize: 16, fontWeight: 'bold' },
      },
      data: s.data
    })),
  };
};


const getCartesianChartOption = (
  data: ChartDataResponse,
  chartType: ChartType,
  styleConfig: ComponentStyleConfig,
  dataConfig?: ComponentConfig
) => {
  const { dimensions, series } = data;
  const isHorizontal = chartType.includes('horizontal');
  const isStacked = chartType.includes('stacked');
  const isLineOrArea = chartType.includes('line') || chartType.includes('area');
  const isArea = chartType.includes('area') || chartType === 'stacked-line'; // Depending on logic

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
  const axisLabelStyle = { ...getTextStyle({ fontSize: styleConfig.xAxisFontSize, color: styleConfig.xAxisColor }) };

  // (Category Axis)
  const categoryAxis = {
    type: 'category',
    data: dimensions,
    show: styleConfig.showAxis ?? true,
    axisLabel: {
      rotate: 0,
      interval: 'auto',
      formatter: function (value) {
        if (!value) return '';
        const lines = value.split('\n');

        const processedLines = lines.map(line => {
          if (line.length > 10) {
            return line.slice(0, 10) + '...';
          }
          return line;
        });

        return processedLines.join('\n');
      },
      hideOverlap: true,
      // interval: 0,
      // hideOverlap: true,
      // overflow: 'break'
      // ...axisLabelStyle,
    },
    name: styleConfig.xAxisTitle || '',
    nameLocation: 'center'
  };

  // (Value Axis)
  const valueAxis = {
    type: 'value',
    show: styleConfig.showAxis ?? true,
    axisLabel: {
      formatter: (val: any) => unitConversion(val, dataConfig).join(''),
      ...axisLabelStyle,
    },
    splitLine: { show: styleConfig.showGrid ?? true },
    name: styleConfig.yAxisTitle || '',
    nameLocation: 'center',
    nameRotate: isHorizontal ? 0 : 90
  };

  // Series
  const cartesianSeries = series.map((s) => {
    const item: any = {
      name: s.name,
      data: s.data,
      type: isLineOrArea ? 'line' : 'bar',
      itemStyle: {
        borderRadius: !isLineOrArea ? (isHorizontal ? [0, 2, 2, 0] : [2, 2, 0, 0]) : 0
      }
    };

    if (styleConfig.showDataLabel) {
      item.label = { show: true, position: isLineOrArea ? 'top' : 'inside' };
    }
    if (isStacked) item.stack = 'total';
    if (isArea) item.areaStyle = {};
    if (isLineOrArea) item.smooth = true;

    return item;
  });

  const dimensionLength = styleConfig.xAxisTitle ? dataConfig.dimensions.length : 1
  const bottom = (styleConfig.legendPosition === 'bottom' ? 44 : 0) + dimensionLength * 13;

  return {
    backgroundColor: styleConfig.bgColor,
    // title: buildTitleOption(styleConfig),
    legend: buildLegendOption(styleConfig, series.map(s => s.name)),
    tooltip: buildTooltipOption('axis', tooltipFormatter),
    grid: {
      left: styleConfig.legendPosition === 'left' ? 160 : 0,
      right: styleConfig.legendPosition === 'right' ? 100 : 0,
      top: styleConfig.legendPosition === 'top' ? 40 : 0,
      bottom,
      // containLabel: true,
    },
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
  // computed
  const orient = pos === 'left' || pos === 'right' ? 'vertical' : 'horizontal';
  const top = pos === 'top' ? 0 : pos === 'bottom' ? 'auto' : 'center';
  const bottom = pos === 'bottom' ? 0 : 'auto';
  const left = pos === 'left' ? 0 : pos === 'center' ? 'center' : 'auto';
  const right = pos === 'right' ? 0 : 'auto';

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
    axisPointer: type === 'axis' ? { type: 'shadow' } : undefined,
    appendToBody: true,
    confine: true,
    enterable: true,
    extraCssText: 'max-height: 500px; overflow-y: auto;',
    formatter,
  };
};
