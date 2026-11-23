import request from '@/controllers/request'

// F016: model prices per million tokens, as decimal strings (never floats).
export type PricingCurrency = 'CNY' | 'USD'
export type PricingSource = 'CATALOG' | 'MANUAL' | 'DEFAULT'

export type ModelPricing = {
    currency: PricingCurrency
    input: string
    cache_read: string
    cache_write?: string | null
    output: string
    // Server-owned fields; echoed back unchanged so the server can detect concurrent edits.
    source?: PricingSource
    catalog_key?: string | null
    catalog_version?: string | null
    ref_key?: string | null
    revision?: number
}

export type PriceCatalogEntry = {
    key: string
    vendor: string
    label: string
    provider_types: string[]
    aliases: string[]
    currency: PricingCurrency
    input: string
    cache_read: string
    cache_write: string | null
    output: string
    source_url: string
    verified_at: string
}

export type PriceCatalogMatch = {
    matched: boolean
    via_name: boolean
    catalog_version: string
    entry: PriceCatalogEntry | null
}

export type PricingHint = { ratio: string | null; base: boolean; free: boolean }

export type CreditSettings = {
    version: number
    currency: PricingCurrency
    credit_value: string
    usd_cny_rate: string
    base_model_id: number | null
    effective_base_model_id?: number | null
    base_reason?: string | null
}

export type ModelPricingRow = {
    model_id: number
    can_edit: boolean
    read_only: boolean
    source_tenant_id: number
    base_reason: string | null
    pricing: ModelPricing | null
    effective: { currency: PricingCurrency; input: string; cache_read: string; cache_write: string; output: string } | null
    edited: boolean
    missing: boolean
    hint: PricingHint
}

// Callers show their own inline state, so none of these requests raises the shared error popup.
export const matchPriceCatalog = (serverType: string, modelName: string, signal?: AbortSignal): Promise<PriceCatalogMatch> =>
    request.get('/api/v1/llm/price-catalog/match', {
        params: { server_type: serverType, model_name: modelName }, signal, silent: true,
    })

export type PriceCatalog = {
    version: string
    entries: PriceCatalogEntry[]
    // Platforms that resell other vendors' models (百炼, 方舟, ...): every entry is offered there.
    multi_vendor_provider_types: string[]
}

export const getPriceCatalog = (signal?: AbortSignal): Promise<PriceCatalog> =>
    request.get('/api/v1/llm/price-catalog', { signal, silent: true })

const admin = '/api/v1/dsh/admin'
export const getCreditSettings = (signal?: AbortSignal): Promise<CreditSettings> =>
    request.get(`${admin}/credit-settings`, { signal, silent: true })
export const saveCreditSettings = (value: CreditSettings): Promise<CreditSettings> =>
    request.put(`${admin}/credit-settings`, {
        version: value.version,
        currency: value.currency,
        credit_value: value.credit_value,
        usd_cny_rate: value.usd_cny_rate,
        base_model_id: value.base_model_id,
    }, { silent: true })
export const getModelPricingRows = (signal?: AbortSignal): Promise<ModelPricingRow[]> =>
    request.get(`${admin}/model-pricing`, { signal, silent: true })
/** Edit one model's price; `revision` is the one last read, so a concurrent edit fails with 10813. */
export const saveModelPricing = (modelId: number, pricing: ModelPricing): Promise<ModelPricing> =>
    request.put(`/api/v1/llm/models/${modelId}/pricing`, {
        currency: pricing.currency,
        input: pricing.input,
        cache_read: pricing.cache_read,
        cache_write: pricing.cache_write || null,
        output: pricing.output,
        revision: pricing.revision ?? null,
    }, { silent: true })

/** A member's current-month balance in credits, as exact decimal strings (same shape as `/dsh/me/credits`). */
export type MonthCredits = {
    month: string
    billing_timezone: string
    reset_at: string
    limit: string
    /** null while the ledger is not ready. */
    used: string | null
    remaining: string | null
    unlimited: boolean
}
/** `preview`: the balance if the user's own credit rule were saved as given (nothing is written). */
export const getUserCredits = (
    userId: number,
    signal?: AbortSignal,
    preview?: { monthly_credits: string; enabled: boolean },
): Promise<MonthCredits> =>
    request.get(`${admin}/users/${userId}/credits`, { params: preview, signal, silent: true })

/** F025 owner capability AND this tenant's explicit restrictions. */
export type ModelVisionRow = {
    model_id: number
    vision: boolean
    effective: boolean
    owner_tenant_id: number | null
    owner_vision: boolean
    source: 'owner' | 'local_restriction' | 'unknown'
    can_edit: boolean
    read_only: boolean
    status: 'available' | 'unavailable'
    reason: string | null
}

export const getModelVisionRows = (modelIds: number[], signal?: AbortSignal): Promise<ModelVisionRow[]> =>
    request.post(`${admin}/model-vision`, { model_ids: modelIds }, { signal, silent: true })
