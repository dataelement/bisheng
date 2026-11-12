import request from '@/controllers/request'

// F015: model prices per million tokens, as decimal strings (never floats).
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
}

export type ModelPricingRow = {
    model_id: number
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
