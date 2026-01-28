"use client"

import { MetricDataResponse } from '@/pages/Dashboard/types/chartData'
import { ArrowDown, ArrowUp, GripHorizontalIcon, Minus } from 'lucide-react'
import { useMemo } from 'react'
import { ComponentStyleConfig, DataConfig } from '../../types/dataConfig'
import { cn } from '@/utils'

interface MetricCardProps {
  data: MetricDataResponse,
  title?: string
  dataConfig?: DataConfig
  styleConfig: ComponentStyleConfig
  isPreviewMode?: boolean
}

export const unitConversion = (value, dataConfig) => {
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
  const finalUnit = unitLabel + (suffix || '');
  // const finalUnit = suffix || unitLabel;

  return [result, finalUnit];
}

export function MetricCard({ title: indicatorName, data, isPreviewMode, dataConfig, styleConfig }: MetricCardProps) {

  const subTitle = styleConfig.subtitle

  // format
  const [formatValue, displayUnit] = useMemo(() => unitConversion(data.value, dataConfig), [dataConfig, data]);

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

  // Build text styles
  const buildTextStyle = (config: {
    fontSize?: number
    bold?: boolean
    italic?: boolean
    underline?: boolean
    strikethrough?: boolean
    color?: string
    align?: 'left' | 'center' | 'right'
  }) => {
    const style: React.CSSProperties = {}
    if (config.fontSize !== undefined) style.fontSize = `${config.fontSize}px`
    if (config.bold) style.fontWeight = 'bold'
    if (config.italic) style.fontStyle = 'italic'
    if (config.color) style.color = config.color
    style.textDecoration = [
      config.underline ? 'underline' : '',
      config.strikethrough ? 'line-through' : ''
    ].filter(Boolean).join(' ') || 'none'
    if (config.align) style.textAlign = config.align
    return style
  }

  const subtitleStyle = buildTextStyle({
    fontSize: styleConfig.subtitleFontSize,
    bold: styleConfig.subtitleBold,
    italic: styleConfig.subtitleItalic,
    underline: styleConfig.subtitleUnderline,
    strikethrough: styleConfig.subtitleStrikethrough,
    color: styleConfig.subtitleColor,
    align: styleConfig.subtitleAlign
  })

  const titleStyle = buildTextStyle({
    fontSize: styleConfig.titleFontSize,
    bold: styleConfig.titleBold,
    italic: styleConfig.titleItalic,
    underline: styleConfig.titleUnderline,
    strikethrough: styleConfig.titleStrikethrough,
    color: styleConfig.titleColor,
    align: styleConfig.titleAlign
  })

  const metricStyle = buildTextStyle({
    fontSize: styleConfig.metricFontSize,
    bold: styleConfig.metricBold,
    italic: styleConfig.metricItalic,
    underline: styleConfig.metricUnderline,
    strikethrough: styleConfig.metricStrikethrough,
    color: styleConfig.metricColor,
    align: styleConfig.metricAlign
  })

  const subtitleLineHeight = styleConfig.subtitleFontSize ? styleConfig.subtitleFontSize * 1.5 : 21 // 默认14px * 1.5
  const maxSubtitleHeight = subtitleLineHeight * 4

  return (
    <div className="group h-full flex flex-col select-none py-1 px-2 pr-1 text-foreground dark:text-gray-400">
      {/* title - single line */}
      <div style={titleStyle} className='truncate mb-1 pr-1'>{indicatorName}</div>

      {/* subtitle - max 4 lines with ellipsis */}
      {styleConfig.showSubtitle &&
        <div
          className='pr-1'
          style={{
            ...subtitleStyle,
            display: '-webkit-box',
            WebkitLineClamp: 4,
            WebkitBoxOrient: 'vertical',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            wordBreak: 'break-all',
            lineHeight: `${subtitleLineHeight}px`,
            maxHeight: `${maxSubtitleHeight}px`,
            flex: 1,
            minHeight: 0
          }}
        >
          {subTitle}
        </div>
      }

      {/* value - stays at bottom */}
      <div className='mt-auto pt-2'>
        <div style={metricStyle} className='leading-[1.2em] truncate pr-1'>
          {formatValue}
          {displayUnit && <span className="text-xl ml-2 text-muted-foreground">{displayUnit}</span>}
        </div>
      </div>

      {!isPreviewMode && <GripHorizontalIcon
        className={cn(
          "absolute top-1 left-1/2 -translate-x-1/2 text-gray-400 transition-opacity",
          "opacity-0",
          "group-hover:opacity-100",
          "group-has-[.no-drag:hover]:opacity-0"
        )}
        size={16}
      />}
    </div>
  )
}