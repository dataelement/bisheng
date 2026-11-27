import request from '@/controllers/request'
import type { CreditSettings, PricingCurrency } from '@/controllers/API/modelPricing'

export type ToolPricingMode = 'MONEY' | 'CREDITS'

export type ToolPricingItem = {
    tool_id: number
    pricing_mode: ToolPricingMode
    currency: PricingCurrency | null
    price: string
    price_micro: number
    call_count: number
    version: number
    estimated_credits: string
    estimated_cost: string | null
    effective_currency: PricingCurrency
}

export type ToolPricingListResponse = {
    credit_setting: CreditSettings
    items: Record<string, ToolPricingItem>
}

export type SaveToolPricingInput = {
    pricing_mode: ToolPricingMode
    currency: PricingCurrency | null
    price: string
    call_count: number
    version: number
}

export function getToolPricingApi(tenantId?: number | null, signal?: AbortSignal): Promise<ToolPricingListResponse> {
    return request.get('/api/v1/dsh/admin/tool-pricing', {
        params: tenantId ? { tenant_id: tenantId } : undefined,
        signal,
        silent: true,
    })
}

export function saveToolPricingApi(
    toolId: number,
    payload: SaveToolPricingInput,
    tenantId?: number | null,
): Promise<ToolPricingItem> {
    return request.put(`/api/v1/dsh/admin/tool-pricing/${toolId}`, payload, {
        params: tenantId ? { tenant_id: tenantId } : undefined,
        silent: true,
    })
}
