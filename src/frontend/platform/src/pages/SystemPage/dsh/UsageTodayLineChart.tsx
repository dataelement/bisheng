import type { DshUsageTimeSummary } from '@/types/dsh'
import { useTranslation } from 'react-i18next'
import {
    Area,
    AreaChart,
    CartesianGrid,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from 'recharts'
import { formatShanghaiInstant } from './usageRange'
import { formatUsageTokens } from './usageTokenFormat'

type Metric = 'tokens' | 'messages'

export function UsageTodayLineChart({
    summary,
    metric,
}: {
    summary: DshUsageTimeSummary
    metric: Metric
}) {
    const { t, i18n } = useTranslation()
    const data = summary.points.map((point) => ({
        time: formatShanghaiInstant(Date.parse(point.start_at)).slice(11, 16),
        value:
            metric === 'tokens'
                ? (point.total_tokens ?? 0)
                : point.message_count,
    }))
    const formatValue = (value: number) =>
        metric === 'tokens'
            ? `${formatUsageTokens(value, i18n.language).compact} Token`
            : t('dsh.heatmapMessageValue', { count: value })
    return (
        <div className="h-56 w-full" data-usage-line-chart={metric}>
            <ResponsiveContainer width="100%" height="100%">
                <AreaChart
                    data={data}
                    margin={{ top: 10, right: 12, bottom: 0, left: 4 }}
                >
                    <defs>
                        <linearGradient
                            id="usageTodayArea"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                        >
                            <stop
                                offset="0%"
                                stopColor="hsl(var(--primary))"
                                stopOpacity={0.24}
                            />
                            <stop
                                offset="100%"
                                stopColor="hsl(var(--primary))"
                                stopOpacity={0.02}
                            />
                        </linearGradient>
                    </defs>
                    <CartesianGrid
                        stroke="hsl(var(--border))"
                        strokeOpacity={0.65}
                    />
                    <XAxis
                        dataKey="time"
                        axisLine={false}
                        tickLine={false}
                        interval={3}
                        tick={{
                            fill: 'hsl(var(--muted-foreground))',
                            fontSize: 12,
                        }}
                    />
                    <YAxis
                        width={64}
                        axisLine={false}
                        tickLine={false}
                        tick={{
                            fill: 'hsl(var(--muted-foreground))',
                            fontSize: 12,
                        }}
                        tickFormatter={(value) =>
                            formatUsageTokens(Number(value), i18n.language)
                                .compact
                        }
                    />
                    <Tooltip
                        isAnimationActive={false}
                        cursor={{ stroke: 'hsl(var(--border))' }}
                        contentStyle={{
                            border: '1px solid hsl(var(--border))',
                            borderRadius: 6,
                            background: 'hsl(var(--background))',
                            color: 'hsl(var(--foreground))',
                            fontSize: 12,
                        }}
                        formatter={(value) => [formatValue(Number(value)), '']}
                        labelStyle={{ color: 'hsl(var(--muted-foreground))' }}
                        itemStyle={{ color: 'hsl(var(--foreground))' }}
                    />
                    <Area
                        type="linear"
                        dataKey="value"
                        stroke="hsl(var(--primary))"
                        strokeWidth={2}
                        fill="url(#usageTodayArea)"
                        dot={{
                            r: 3,
                            strokeWidth: 2,
                            stroke: 'hsl(var(--background))',
                            fill: 'hsl(var(--primary))',
                        }}
                        activeDot={{
                            r: 5,
                            strokeWidth: 2,
                            stroke: 'hsl(var(--primary))',
                            fill: 'hsl(var(--background))',
                        }}
                        isAnimationActive={false}
                    />
                </AreaChart>
            </ResponsiveContainer>
        </div>
    )
}
