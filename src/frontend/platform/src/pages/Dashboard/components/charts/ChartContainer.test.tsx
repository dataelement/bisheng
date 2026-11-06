import { QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPlatformQueryClient } from '@/queryClient';
import { ChartType, type DashboardComponent } from '../../types/dataConfig';
import { ChartContainer } from './ChartContainer';

const mock = vi.hoisted(() => ({ query: vi.fn(), state: {
  chartRefreshTriggers: {} as Record<string, { trigger: number; queryParams: unknown[] }>,
  currentDashboard: { id: 'dashboard-1' },
} }));
vi.mock('@/controllers/API/dashboard', () => ({ queryChartData: mock.query }));
vi.mock('@/store/dashboardStore', () => ({ useEditorDashboardStore: (select: (state: typeof mock.state) => unknown) => select(mock.state) }));
vi.mock('./BaseChart', () => ({ BaseChart: () => <div>Rendered chart</div> }));
vi.mock('./MetricCard', () => ({ MetricCard: () => null }));
const component = { id: 'chart-1', type: ChartType.Bar, data_config: { isConfigured: true } } as DashboardComponent;
beforeEach(() => { mock.query.mockReset(); mock.state.chartRefreshTriggers = {}; });
afterEach(cleanup);

it('does not show a pending spinner or fetch before a manual chart trigger', () => {
  const client = createPlatformQueryClient();
  render(<QueryClientProvider client={client}><ChartContainer component={component} isDark={false} isPreviewMode={false} /></QueryClientProvider>);
  expect(screen.getByText('noDataInChart')).toBeInTheDocument();
  expect(screen.queryByText('updatingCharts')).not.toBeInTheDocument();
  expect(mock.query).not.toHaveBeenCalled();
  client.clear();
});

it('keeps a failed chart query distinguishable from a successful empty chart', async () => {
  mock.query.mockRejectedValue(new Error('Chart unavailable'));
  mock.state.chartRefreshTriggers['chart-1'] = { trigger: 1, queryParams: [] };
  const client = createPlatformQueryClient();
  render(<QueryClientProvider client={client}><ChartContainer component={component} isDark={false} isPreviewMode={false} /></QueryClientProvider>);
  expect(await screen.findByText('operationFailed')).toBeInTheDocument();
  expect(screen.queryByText('noDataInChart')).not.toBeInTheDocument();
  expect(client.getQueryState(['chartData', 'chart-1', 1])?.status).toBe('error');
  client.clear();
});

it('shows loading during a manual request and then renders the returned chart', async () => {
  let finish: (value: { dimensions: string[]; series: unknown[] }) => void = () => undefined;
  mock.query.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const client = createPlatformQueryClient();
  const view = () => <QueryClientProvider client={client}><ChartContainer component={component} isDark={false} isPreviewMode={false} /></QueryClientProvider>;
  const { rerender } = render(view());
  mock.state.chartRefreshTriggers['chart-1'] = { trigger: 1, queryParams: [] };
  rerender(view());
  await waitFor(() => expect(mock.query).toHaveBeenCalledTimes(1));
  expect(await screen.findByText('updatingCharts')).toBeInTheDocument();
  await act(async () => { finish({ dimensions: ['A'], series: [] }); });
  expect(await screen.findByText('Rendered chart')).toBeInTheDocument();
  expect(screen.queryByText('updatingCharts')).not.toBeInTheDocument();
  client.clear();
});
