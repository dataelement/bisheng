"use client"

import { ChartType, ComponentConfig } from '@/pages/Dashboard/types/dataConfig'
import { useEffect, useRef, useState } from 'react'
import { ChartDataResponse } from '../../types/chartData'

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
  dataConfig?: ComponentConfig // Chart component configuration.
  height?: number
}

export function BaseChart({ data, chartType, dataConfig, height = 300 }: BaseChartProps) {
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

    try {
      // init echarts
      chartRef.current = echartsLibRef.current.init(domRef.current)
      const option = generateChartOption(data, chartType, dataConfig)
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
  }, [echartsLibRef.current, data, chartType, dataConfig, isLoading])

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

  return <div ref={domRef} style={{ width: '100%', height: `${height}px` }} />
}

/**
 * Generate ECharts configuration based on chart type and data.
 */
function generateChartOption(data: ChartDataResponse, chartType: ChartType, dataConfig?: ComponentConfig): any {
  const { dimensions, series } = data

  // Determine whether it is a stacked chart (judged by chartType).
  const isStacked = chartType.includes('stacked')

  // Determine whether it is an area chart.
  const isArea = chartType === 'area' || chartType === 'stacked-line'

  // Pie chart and donut chart.
  if (chartType === 'pie' || chartType === 'donut') {
    return {
      tooltip: {
        trigger: 'item',
        formatter: '{a} <br/>{b}: {c} ({d}%)'
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
      }
    },
    legend: {
      data: series.map(s => s.name),
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
      type: 'value'
    };
    option.yAxis = {
      type: 'category',
      data: dimensions
    };
  } else {
    // Column chart/line chart: X-axis is category axis, Y-axis is value axis
    option.xAxis = {
      type: 'category',
      data: dimensions,
      axisLabel: {
        rotate: dimensions.length > 10 ? 45 : 0
      }
    };
    option.yAxis = {
      type: 'value'
    };
  }

  // Set series
  option.series = series.map((s, index) => {
    let seriesType: 'bar' | 'line' = 'bar';
    const seriesConfig: any = {
      name: s.name,
      data: s.data
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
