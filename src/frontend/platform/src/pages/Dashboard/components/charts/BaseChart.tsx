"use client"

import { ChartType, ComponentConfig, ComponentStyleConfig } from '@/pages/Dashboard/types/dataConfig'
import { useEffect, useRef, useState } from 'react'
import { ChartDataResponse } from '../../types/chartData'
import { colorSchemes, convertToEChartsTheme } from '../../colorSchemes'
import { useEditorDashboardStore } from '@/store/dashboardStore'

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
      const theme = 'professional-blue'
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
        <div className="text-sm text-muted-foreground">加载图表中...</div>
      </div>
    )
  }

  return <div ref={domRef} style={{ width: '100%', height: `100%` }} />
}

/**
 * Generate ECharts configuration based on chart type and data.
 */
function generateChartOption({ data, chartType, dataConfig, styleConfig }
  : { data: ChartDataResponse, chartType: ChartType, dataConfig?: ComponentConfig, styleConfig: ComponentStyleConfig }): any {
  const { dimensions, series } = data

  const computedUnit = (value) => {
    // console.log('dataConfig :>> ', dataConfig);
    return value + '元'
  }

  // Determine whether it is a stacked chart (judged by chartType).
  const isStacked = chartType.includes('stacked')

  // Determine whether it is an area chart.
  const isArea = chartType === 'area' || chartType === 'stacked-line'

  // Pie chart and donut chart.
  if (chartType === 'pie' || chartType === 'donut') {
    return {
      tooltip: {
        trigger: 'item',
        // formatter: '{a} <br/>{b}: {c} ({d}%)'
        formatter: function (params) {
          return `${params.name.replaceAll('\n', '<br/>')}: ${params.value} (${params.percent}%)`;
        }
      },
      legend: {
        orient: 'vertical',
        right: 10,
        top: 'center'
      },
      series: series.map(s => ({
        name: s.name,
        type: 'pie',
        radius: chartType === 'donut' ? ['40%', '70%'] : '70%',
        avoidLabelOverlap: true,
        itemStyle: {
          borderRadius: 10,
          borderColor: '#fff',
          borderWidth: 2
        },
        label: {
          show: true,
          formatter: '{b}: {d}%'
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 16,
            fontWeight: 'bold'
          }
        },
        data: s.data
      }))
    }
  }


  // base
  const option: any = {
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow'
      },
      formatter: function (params) {
        // params 是一个数组，包含当前轴点上的所有系列数据
        let res = params[0].name.replaceAll('\n', '<br/>') + '<br/>'; // 第一行显示 X 轴的值（如：周一）

        params.forEach(item => {
          // item.marker 是对应系列颜色的小圆点
          // item.seriesName 是系列名称
          // item.value 是当前数值
          res += `${item.marker} ${item.seriesName}: <b>${computedUnit(item.value)}</b><br/>`;
        });

        return res;
      }
    },
    legend: {
      data: series.map(s => s.name), // 多指标 堆叠维度
      top: 0
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      containLabel: true
    }
  }

  // Bar chart (horizontal)
  const isHorizontal = chartType.includes('horizontal');
  // Set coordinate axes
  if (isHorizontal) {
    // Bar chart: X-axis is value axis, Y-axis is category axis
    option.xAxis = {
      type: 'value',
      axisLabel: {
        formatter: function (value) {
          return computedUnit(value)
        }
      }
    };
    option.yAxis = {
      type: 'category',
      data: dimensions  // 多维度拼\n
    };
  } else {
    // Column chart/line chart: X-axis is category axis, Y-axis is value axis
    option.xAxis = {
      type: 'category',
      data: dimensions,
      axisLabel: {
        rotate: dimensions.length > 10 ? 45 : 0  // 多维度拼\n
      }
    };
    option.yAxis = {
      type: 'value',
      axisLabel: {
        formatter: function (value) {
          return computedUnit(value)
        }
      }
    };
  }

  // Set series
  option.series = series.map((s, index) => {
    let seriesType: 'bar' | 'line' = 'bar';
    const seriesConfig: any = {
      name: s.name,
      data: s.data,
      itemStyle: {
        borderRadius: isHorizontal ? [0, 2, 2, 0] : [2, 2, 0, 0]
      }
    };

    // Set series type based on chart type
    if (chartType.includes('line') || chartType === 'area') {
      seriesType = 'line';
    }

    seriesConfig.type = seriesType;

    // Stacking configuration (all series in stacked chart use the same stack value)
    if (isStacked) {
      seriesConfig.stack = 'total';
    }

    // Area chart configuration
    if (isArea) {
      seriesConfig.areaStyle = {};
    }

    // Smooth curve (line chart)
    if (seriesType === 'line') {
      seriesConfig.smooth = true;
    }

    return seriesConfig;
  });

  return option
}

