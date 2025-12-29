"use client"

import { MetricDataResponse } from '@/pages/Dashboard/types/chartData'
import { ArrowUp, ArrowDown, Minus } from 'lucide-react'

interface MetricCardProps {
  data: MetricDataResponse
}

export function MetricCard({ data }: MetricCardProps) {
  const { value, title, unit, trend, format } = data

  // 格式化数值
  const formatValue = (val: number): string => {
    let formatted = val.toString()

    // 应用小数位数
    if (format?.decimalPlaces !== undefined) {
      formatted = val.toFixed(format.decimalPlaces)
    }

    // 应用千分位符
    if (format?.thousandSeparator) {
      const parts = formatted.split('.')
      parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',')
      formatted = parts.join('.')
    }

    return formatted
  }

  // 获取趋势图标
  const getTrendIcon = () => {
    if (!trend) return null

    const iconClass = "h-4 w-4"
    switch (trend.direction) {
      case 'up':
        return <ArrowUp className={`${iconClass} text-green-500`} />
      case 'down':
        return <ArrowDown className={`${iconClass} text-red-500`} />
      case 'flat':
        return <Minus className={`${iconClass} text-gray-500`} />
    }
  }

  // 获取趋势颜色
  const getTrendColor = () => {
    if (!trend) return ''

    switch (trend.direction) {
      case 'up':
        return 'text-green-500'
      case 'down':
        return 'text-red-500'
      case 'flat':
        return 'text-gray-500'
    }
  }

  return (
    <div className="flex flex-col items-center justify-center h-full p-6">
      {/* 主要数值 */}
      <div className="text-5xl font-bold text-primary mb-2">
        {formatValue(value)}
        {unit && <span className="text-2xl ml-2 text-muted-foreground">{unit}</span>}
      </div>

      {/* 标题 */}
      <div className="text-lg text-muted-foreground mb-3">{title}</div>

      {/* 趋势信息 */}
      {trend && (
        <div className="flex items-center gap-1 text-sm">
          {getTrendIcon()}
          <span className={getTrendColor()}>
            {trend.value > 0 ? '+' : ''}{trend.value}%
          </span>
          <span className="text-muted-foreground ml-1">{trend.label}</span>
        </div>
      )}
    </div>
  )
}
