import type { DshUsageTimeSummary } from '@/types/dsh'
import { useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { buildUsageHeatmap } from './usageHeatmapData'
import { formatShanghaiInstant } from './usageRange'
import { USAGE_TILE_GAP, USAGE_TILE_SIZE } from './useUsageCalendarWidth'
import { formatUsageTokens } from './usageTokenFormat'
import { messageHeatLevel, USAGE_HEAT_COLORS, usageHeatLevel } from './usageHeatScale'

type UsageHeatmapMetric = 'tokens' | 'messages'

interface UsageHeatmapProps {
    summary: DshUsageTimeSummary
    metric?: UsageHeatmapMetric
}

interface ActiveTooltip {
    key: string
    time: string
    value: string
    status: string | null
    missingUsage: string | null
    left: number
    top: number
    placement: 'top' | 'bottom'
    arrowOffset: number
}

export function UsageHeatmap({ summary, metric = 'tokens' }: UsageHeatmapProps) {
    const scrollRef = useRef<HTMLDivElement>(null)
    const tooltipId = useId()
    const [activeTooltip, setActiveTooltip] = useState<ActiveTooltip | null>(null)
    const { t, i18n } = useTranslation()
    const layout = buildUsageHeatmap(summary)
    const unit = layout.hoursPerTile < 24 ? 'hour' : 'day'
    const columns = `repeat(${layout.columns}, ${USAGE_TILE_SIZE}px)`
    const gridRows = `repeat(${layout.rows}, ${USAGE_TILE_SIZE}px)`
    const hasRowLabels = layout.rowLabels.length > 0
    const plotWidth = layout.columns * (USAGE_TILE_SIZE + USAGE_TILE_GAP) - USAGE_TILE_GAP
    const activityLabel = t(metric === 'tokens' ? 'dsh.tokenActivity' : 'dsh.messageActivity')
    useLayoutEffect(() => {
        const element = scrollRef.current
        if (element)
            element.scrollLeft = layout.mode === 'calendar' ? element.scrollWidth - element.clientWidth : 0
    }, [layout.mode, layout.columns, summary.start_at, summary.end_at])
    // Keep short year markers at boundaries and leave room for adjacent month labels.
    const columnLabels = layout.columnLabels.filter(
        (item, index, labels) =>
            index === 0 || !/^\d{4}-\d{2}$/.test(item.label) || item.column - labels[index - 1].column >= 3,
    )
    const showTooltip = (element: HTMLButtonElement, tooltip: Omit<ActiveTooltip, 'left' | 'top' | 'placement' | 'arrowOffset'>) => {
        const rect = element.getBoundingClientRect()
        const anchor = rect.left + rect.width / 2
        const halfWidth = 125
        const left = Math.min(Math.max(anchor, halfWidth + 8), window.innerWidth - halfWidth - 8)
        const placement = rect.top < 96 ? 'bottom' : 'top'
        setActiveTooltip({
            ...tooltip,
            left,
            top: placement === 'top' ? rect.top - 10 : rect.bottom + 10,
            placement,
            arrowOffset: anchor - left,
        })
    }
    return (
        <>
            <div ref={scrollRef} className="w-full overflow-x-auto px-2 py-2" data-heatmap-layout={layout.mode}>
                <div
                    className="grid w-max gap-y-2"
                    style={{
                        gridTemplateColumns: hasRowLabels ? `max-content ${plotWidth}px` : `${plotWidth}px`,
                        columnGap: hasRowLabels ? 12 : undefined,
                    }}
                >
                    <div
                        className="grid h-4 text-xs leading-none text-muted-foreground"
                        style={{
                            gridTemplateColumns: columns,
                            gap: USAGE_TILE_GAP,
                            gridColumn: hasRowLabels ? 2 : 1,
                        }}
                    >
                        {columnLabels.map(({ column, label }, index) => (
                            <span
                                key={`${column}-${label}`}
                                className="whitespace-nowrap"
                                title={label}
                                style={{
                                    gridRow: 1,
                                    gridColumn: `${column + 1} / span ${Math.min(4, layout.columns - column)}`,
                                    textAlign: column === layout.columns - 1 ? 'right' : undefined,
                                }}
                            >
                                {/^(\d{4})-(\d{2})$/.test(label)
                                    ? index === 0 || label.endsWith('-01')
                                        ? label.slice(0, 4)
                                        : new Intl.DateTimeFormat(i18n.language, {
                                              month: 'short',
                                              timeZone: 'Asia/Shanghai',
                                          }).format(new Date(`${label}-01T00:00:00+08:00`))
                                    : label}
                            </span>
                        ))}
                    </div>
                    {hasRowLabels && (
                        <div
                            className="grid text-xs leading-none text-muted-foreground"
                            style={{ gridRow: 2, gridColumn: 1, gridTemplateRows: gridRows, gap: USAGE_TILE_GAP }}
                        >
                            {layout.rowLabels.map(({ label, row }) => (
                                <span key={`${row}-${label}`} className="flex items-center whitespace-nowrap tabular-nums" style={{ gridRow: row + 1 }}>
                                    {label}
                                </span>
                            ))}
                        </div>
                    )}
                    <ol
                        aria-label={activityLabel}
                        data-heatmap-metric={metric}
                        data-rows={layout.rows}
                        data-columns={layout.columns}
                        className="grid"
                        onPointerLeave={() => setActiveTooltip(null)}
                        onBlur={(event) => {
                            if (!event.currentTarget.contains(event.relatedTarget)) setActiveTooltip(null)
                        }}
                        onKeyDown={(event) => {
                            if (event.key === 'Escape') setActiveTooltip(null)
                        }}
                        style={{
                            gridTemplateColumns: columns,
                            gridTemplateRows: gridRows,
                            gridColumn: hasRowLabels ? 2 : 1,
                            gridRow: 2,
                            gap: USAGE_TILE_GAP,
                        }}
                    >
                        {layout.tiles.map((tile) => {
                            const { point } = tile
                            const future = tile.state === 'future'
                            const outside = tile.state === 'outside'
                            const unknown = metric === 'tokens' && Boolean(point && point.missing_usage_count > 0)
                            const level =
                                metric === 'tokens'
                                    ? usageHeatLevel(point?.total_tokens ?? null, unit)
                                    : messageHeatLevel(point?.message_count ?? null, unit)
                            const start = formatShanghaiInstant(Date.parse(tile.startAt))
                                .slice(0, 16)
                                .replace('T', ' ')
                            const end = formatShanghaiInstant(Date.parse(tile.endAt))
                                .slice(0, 16)
                                .replace('T', ' ')
                            const time = layout.hoursPerTile === 24 ? start.slice(0, 10) : `${start} – ${end}`
                            const amount =
                                point?.total_tokens == null
                                    ? null
                                    : formatUsageTokens(point.total_tokens, i18n.language)
                            const tokens = amount?.exact ?? t('dsh.unavailable')
                            const tokenValue = t('dsh.heatmapTokenValue', {
                                exact: amount?.compact ?? tokens,
                            })
                            const displayedValue =
                                metric === 'tokens'
                                    ? tokenValue
                                    : t('dsh.heatmapMessageValue', {
                                          value: (point?.message_count ?? 0).toLocaleString(i18n.language),
                                      })
                            const label =
                                future || outside
                                    ? `${time} · ${t(future ? 'dsh.heatmapFuture' : 'dsh.heatmapOutside')}`
                                    : t('dsh.heatmapTile', {
                                          time,
                                          tokens,
                                          messages: point?.message_count ?? 0,
                                      })
                            const tooltip = {
                                key: tile.startAt,
                                time,
                                value: displayedValue,
                                status:
                                    future || outside
                                        ? t(future ? 'dsh.heatmapFuture' : 'dsh.heatmapOutside')
                                        : null,
                                missingUsage: unknown
                                    ? t('dsh.missingUsageCount', {
                                          count: point!.missing_usage_count,
                                      })
                                    : null,
                            }
                            return (
                                <li
                                    key={tile.startAt}
                                    className="min-h-0 min-w-0"
                                    style={{ gridRow: tile.row + 1, gridColumn: tile.column + 1 }}
                                >
                                    <button
                                        type="button"
                                        aria-label={label}
                                        aria-describedby={activeTooltip?.key === tile.startAt ? tooltipId : undefined}
                                        data-heat-level={future || outside ? undefined : level}
                                        data-future={future || undefined}
                                        data-usage-unknown={unknown || undefined}
                                        style={{ width: USAGE_TILE_SIZE, height: USAGE_TILE_SIZE }}
                                        className={`relative block aspect-square rounded-[2px] border-0 p-0 hover:outline hover:outline-1 hover:outline-offset-1 hover:outline-foreground/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 ${future || outside ? 'bg-muted/50' : USAGE_HEAT_COLORS[level]}`}
                                        onPointerEnter={(event) => showTooltip(event.currentTarget, tooltip)}
                                        onFocus={(event) => showTooltip(event.currentTarget, tooltip)}
                                    >
                                        {tile.label}
                                        {unknown && (
                                            <span
                                                aria-hidden="true"
                                                className="absolute right-0.5 top-0.5 size-1 rounded-full bg-amber-500"
                                            />
                                        )}
                                    </button>
                                </li>
                            )
                        })}
                    </ol>
                </div>
            </div>
            {activeTooltip &&
                createPortal(
                    <div
                        id={tooltipId}
                        role="tooltip"
                        data-placement={activeTooltip.placement}
                        className="pointer-events-none fixed z-[130] max-w-[250px] space-y-1 overflow-visible rounded-md bg-black-button px-3 py-1.5 text-xs text-white shadow-md"
                        style={{
                            left: activeTooltip.left,
                            top: activeTooltip.top,
                            transform:
                                activeTooltip.placement === 'top'
                                    ? 'translate(-50%, -100%)'
                                    : 'translate(-50%, 0)',
                        }}
                    >
                        <p className="opacity-80">{activeTooltip.time}</p>
                        <p className="font-medium tabular-nums">
                            {activeTooltip.status ?? activeTooltip.value}
                        </p>
                        {activeTooltip.missingUsage && <p>{activeTooltip.missingUsage}</p>}
                        <span
                            aria-hidden="true"
                            className={`absolute size-2 -translate-x-1/2 rotate-45 bg-black-button ${
                                activeTooltip.placement === 'top' ? '-bottom-1' : '-top-1'
                            }`}
                            style={{ left: `calc(50% + ${activeTooltip.arrowOffset}px)` }}
                        />
                    </div>,
                    document.body,
                    'usage-heatmap-tooltip',
                )}
        </>
    )
}
