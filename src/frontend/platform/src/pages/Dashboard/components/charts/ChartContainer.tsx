"use client"

import { useEffect } from 'react'
import { useQuery } from 'react-query'
import { queryChartData } from '@/controllers/API/dashboard'
import { DashboardComponent } from '@/pages/Dashboard/types/dataConfig'
import { ChartDataResponse, MetricDataResponse } from '@/pages/Dashboard/types/chartData'
import { BaseChart } from './BaseChart'
import { MetricCard } from './MetricCard'
import { RefreshCw } from 'lucide-react'
import { useEditorDashboardStore } from '@/store/dashboardStore'

interface ChartContainerProps {
  isDark: boolean;
  component: DashboardComponent;
}

export function ChartContainer({ isDark, component }: ChartContainerProps) {
  const chartRefreshTriggers = useEditorDashboardStore(state => state.chartRefreshTriggers)
  const refreshInfo = chartRefreshTriggers[component.id]
  const refreshTrigger = refreshInfo?.trigger || 0
  const queryParams = refreshInfo?.queryParams || []

  // Query chart data
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['chartData', component.id, refreshTrigger],
    queryFn: () => queryChartData({
      componentId: component.id,
      chartType: component.type,
      dataConfig: component.data_config,
      queryParams: queryParams  //  Pass parameters for the query component 
    }),
    enabled: !!component.id
  });

  // Refetch when refresh trigger changes
  useEffect(() => {
    if (refreshTrigger > 0) {
      refetch()
    }
  }, [refreshTrigger, refetch])

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-2">
          <RefreshCw className="h-8 w-8 animate-spin text-primary" />
          <span className="text-sm text-muted-foreground">加载中...</span>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-2">
          <span className="text-sm text-destructive">加载失败</span>
        </div>
      </div>
    );
  }

  // No data
  if (!data) {
    return (
      <div className="flex items-center justify-center h-full">
        <span className="text-sm text-muted-foreground">暂无数据</span>
      </div>
    );
  }

  // Render metric card
  if (component.type === 'metric') {
    return <MetricCard
      isDark={isDark}
      data={data as MetricDataResponse}
      dataConfig={component.data_config}
      styleConfig={component.style_config} />;
  }

  // Render chart
  return (
    <div className="relative h-full">
      <BaseChart
        isDark={isDark}
        data={data as ChartDataResponse}
        chartType={component.type}
        dataConfig={component.data_config}
        styleConfig={component.style_config}
      />
    </div>
  );
}