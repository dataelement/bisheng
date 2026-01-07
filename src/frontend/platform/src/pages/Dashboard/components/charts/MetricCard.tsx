"use client"

import { MetricDataResponse } from '@/pages/Dashboard/types/chartData'
import { ArrowDown, ArrowUp, Minus } from 'lucide-react'
import { useMemo } from 'react'
import { ComponentStyleConfig, DataConfig } from '../../types/dataConfig'

interface MetricCardProps {
  data: MetricDataResponse
  isDark: boolean
  dataConfig?: DataConfig
  styleConfig: ComponentStyleConfig
}

export const unitConversion = (data, dataConfig) => {
  if (!data) return ['', '']
  const { value } = data
  if (!dataConfig.metrics?.length || value === undefined || value === null) {
    return [value, ''];
  }

  const { type, decimalPlaces = 0, unit, suffix, thousandSeparator } = dataConfig.metrics[0].numberFormat;
  let formattedNumber = Number(value);
  let unitLabel = '';
  let divisor = 1;

  switch (type) {
    case 'number': {
      const numberMap = { 'None': 1, 'Thousand': 1e3, 'Million': 1e6, 'Billion': 1e9 };
      const labels = { 'None': '', 'Thousand': 'K', 'Million': 'M', 'Billion': 'B' };
      divisor = numberMap[unit] || 1;
      unitLabel = labels[unit] || '';
      break;
    }
    case 'percent': {
      formattedNumber = formattedNumber * 100;
      unitLabel = '%';
      break;
    }
    case 'duration': {
      const durationMap = { 'ms': 1, 's': 1000, 'min': 60000, 'hour': 3600000 };
      divisor = durationMap[unit] || 1;
      unitLabel = unit || 'ms';
      break;
    }
    case 'storage': {
      const storageMap = { 'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4 };
      divisor = storageMap[unit] || 1;
      unitLabel = unit || 'B';
      break;
    }
    default:
      divisor = 1;
  }

  // 换算
  formattedNumber = formattedNumber / divisor;

  // 应用小数位数 (限制 0-5 位)
  const safeDecimals = Math.min(Math.max(decimalPlaces, 0), 5);
  let result = formattedNumber.toFixed(safeDecimals);

  // 应用千分位符
  if (thousandSeparator) {
    const parts = result.split('.');
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    result = parts.join('.');
  }

  // 处理后缀
  const finalUnit = suffix || unitLabel;

  return [result, finalUnit];
}

export function MetricCard({ data, dataConfig, styleConfig, isDark }: MetricCardProps) {
  console.log('data :>> ', data);
  const indicatorName = '指标名称'
  const subTitle = '副标题' // style中获取

  // format
  const [formatValue, displayUnit] = useMemo(() => unitConversion(dataConfig, data), [dataConfig, data]);

  // 获取趋势图标
  const getTrendIcon = () => {
    if (!data.trend) return null

    const iconClass = "h-4 w-4"
    switch (data.trend.direction) {
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
    if (!data.trend) return ''

    switch (data.trend.direction) {
      case 'up':
        return 'text-green-500'
      case 'down':
        return 'text-red-500'
      case 'flat':
        return 'text-gray-500'
    }
  }

  return (
    <div className="flex items-end justify-between h-full">
      <div className='flex flex-col h-full justify-between'>
        {/* subtitle */}
        <div className="text-sm text-[#666]">{subTitle}</div>
        {/* title */}
        <div className="text-sm text-blod text-[#0F172A]">{indicatorName}</div>
      </div>
      {/* value */}
      <div className="text-2xl text-[#0EA5E9] font-bold">
        {formatValue}
        {displayUnit && <span className="text-xl ml-2 text-muted-foreground">{displayUnit}</span>}
      </div>


      {/* 趋势信息 */}
      {/* {trend && (
        <div className="flex items-center gap-1 text-sm">
          {getTrendIcon()}
          <span className={getTrendColor()}>
            {trend.value > 0 ? '+' : ''}{trend.value}%
          </span>
          <span className="text-muted-foreground ml-1">{trend.label}</span>
        </div>
      )} */}
    </div>
  )
}
