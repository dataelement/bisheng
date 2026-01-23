"use client"

import { queryChartData } from '@/controllers/API/dashboard'
import { ChartDataResponse, MetricDataResponse } from '@/pages/Dashboard/types/chartData'
import { ChartType, DashboardComponent } from '@/pages/Dashboard/types/dataConfig'
import { useEditorDashboardStore } from '@/store/dashboardStore'
import { useEffect } from 'react'
import { useQuery } from 'react-query'
import { BaseChart } from './BaseChart'
import { MetricCard } from './MetricCard'
import { useTranslation } from 'react-i18next'

interface ChartContainerProps {
  isDark: boolean;
  isPreviewMode: boolean;
  component: DashboardComponent;
}

export function ChartContainer({ isPreviewMode, isDark, component }: ChartContainerProps) {
  const { t } = useTranslation("dashboard")

  const chartRefreshTriggers = useEditorDashboardStore(state => state.chartRefreshTriggers)
  const currentDashboard = useEditorDashboardStore(state => state.currentDashboard)
  const refreshInfo = chartRefreshTriggers[component.id]
  const refreshTrigger = refreshInfo?.trigger || 0
  const queryParams = refreshInfo?.queryParams || []

  // Query chart data
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['chartData', component.id, refreshTrigger],
    queryFn: () => queryChartData({
      useId: isPreviewMode,
      dashboardId: currentDashboard?.id,
      component,
      queryParams
    }),
    enabled: !!component.id && component.data_config.isConfigured
  });

  // Refetch when refresh trigger changes
  useEffect(() => {
    if (refreshTrigger > 0) {
      console.log('refreshInfo :>> ', component, refreshInfo);
      refetch()
    }
  }, [refreshTrigger, refetch])

  // Loading state
  if (isLoading) {
    return (
      <div className="relative w-full h-full flex items-center justify-center overflow-hidden rounded-xl border border-[#f0f7ff] bg-[#f8fbff]">
        <div
          className="absolute inset-0 animate-shimmer"
          style={{
            background: 'linear-gradient(90deg, rgba(191, 219, 253, 0.01) 30%,  #fff 50%, rgba(191, 219, 253, 0.01) 70%)',
            backgroundSize: '200% 100%',
          }}
        />

        <div className="relative z-10 bg-white px-6 py-2 rounded-md backdrop-blur-sm">
          <div className="flex items-center gap-3">
            <span className="text-[#8da9ff] font-medium text-lg tracking-wider break-keep">
              {t('updatingCharts')}
            </span>
          </div>
        </div>

        <style>{`
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        .animate-shimmer {
          animation: shimmer 3s infinite linear;
        }
      `}</style>
      </div>
    );
  }

  // No data
  // if (error || !component.data_config.isConfigured) {
  if (error || !component.data_config.isConfigured || !data) {
    return (
      <div className={`flex items-center justify-center h-full relative ${component.type === ChartType.Metric && 'pt-4'}`}>
        {component.type === ChartType.Metric && <h3 className="absolute top-0 left-0 text-sm font-medium truncate dark:text-gray-400">
          <span className="no-drag cursor-pointer">{component.title}</span>
        </h3>}
        <img src={`${__APP_ENV__.BASE_URL}/assets/dashboard/ept-${component.type}.png`} className="w-full max-h-full max-w-60" />
        <div className='flex size-full absolute justify-center items-center'>
          <span className="text-sm bg-gray-50/80 px-2 py-1 text-primary truncate">{t('noDataInChart')}</span>
        </div>
      </div>
    );
  }

  // Render metric card
  if (component.type === 'metric') {
    return <MetricCard
      title={component.title}
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