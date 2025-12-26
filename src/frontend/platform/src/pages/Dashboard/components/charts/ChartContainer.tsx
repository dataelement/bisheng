"use client"

import { useEffect, useState } from 'react'
import { useQuery } from 'react-query'
import { queryChartData } from '@/controllers/API/dashboard'
import { DashboardComponent } from '@/pages/Dashboard/types/dataConfig'
import { ChartDataResponse, MetricDataResponse } from '@/pages/Dashboard/types/chartData'
import { BaseChart } from './BaseChart'
import { MetricCard } from './MetricCard'
import { Button } from '@/components/bs-ui/button'
import { RefreshCw } from 'lucide-react'

interface ChartContainerProps {
  component: DashboardComponent;
  queryTrigger?: number; // Query trigger, re-query when changed
}

export function ChartContainer({ component, queryTrigger = 0 }: ChartContainerProps) {
  console.log('component :>> ', component);
  const [localTrigger, setLocalTrigger] = useState(0);

  // Combine external trigger and local trigger
  const finalTrigger = queryTrigger + localTrigger;

  // Query chart data
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['chartData', component.id, finalTrigger],
    queryFn: () => queryChartData({
      componentId: component.id,
      chartType: component.type,
      dataConfig: component.data_config,
      queryParams: [] // Traverse query components to check if current component exists, add to queryParams if present
    }),
    enabled: !!component.id
  });

  // Manual trigger for query
  const handleRefresh = () => {
    setLocalTrigger(prev => prev + 1);
  };

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
          <Button size="sm" variant="outline" onClick={handleRefresh}>
            重试
          </Button>
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
    return <MetricCard data={data as MetricDataResponse} />;
  }

  // Render chart
  return (
    <div className="relative h-full">
      {/* Refresh button (temporary, for testing) */}
      <Button
        size="icon"
        variant="ghost"
        className="absolute top-2 right-2 z-10 h-6 w-6"
        onClick={handleRefresh}
      >
        <RefreshCw className="h-3 w-3" />
      </Button>
      <BaseChart
        data={data as ChartDataResponse}
        chartType={component.type}
        dataConfig={component.data_config}
        height={300}
      />
    </div>
  );
}