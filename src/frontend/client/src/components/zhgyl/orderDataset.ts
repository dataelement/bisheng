import { useQuery } from '@tanstack/react-query';
import request from '~/api/request';
import { validateOrderDataset } from './orderContracts';
export type { WorkspaceOrder, OrderDataset, OrderLine, OrderInvoice, OrderSettlement } from './orderContracts';

export function useOrderDataset(enabled: boolean) {
  return useQuery({ queryKey: ['zhgylOrderDataset'], queryFn: async () => validateOrderDataset(await request.get<unknown>('/api/zhgyl/orders')), enabled, retry: false, staleTime: 30000 });
}
