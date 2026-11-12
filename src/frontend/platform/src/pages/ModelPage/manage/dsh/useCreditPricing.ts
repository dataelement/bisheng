import {
    getCreditSettings,
    getModelPricingRows,
    saveCreditSettings,
    type CreditSettings,
} from '@/controllers/API/modelPricing'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

const creditSettingsKey = ['dsh-credit-pricing', 'settings'] as const
const modelPricingKey = ['dsh-credit-pricing', 'models'] as const
// Prices and ratios change from other pages (model configuration), so always read them fresh.
const fresh = { retry: false, cacheTime: 0, staleTime: 0, refetchOnWindowFocus: false } as const

export function useCreditSettings(enabled = true) {
    const client = useQueryClient()
    const settings = useQuery({
        queryKey: creditSettingsKey,
        queryFn: ({ signal }) => getCreditSettings(signal),
        enabled,
        ...fresh,
    })
    const mutation = useMutation({
        mutationFn: (value: CreditSettings) => saveCreditSettings(value),
        retry: false,
        onSuccess: (value) => {
            client.setQueryData(creditSettingsKey, value)
            // Ratios and converted prices depend on the base model, the currency and the rate.
            void client.invalidateQueries({ queryKey: modelPricingKey })
        },
    })
    return { settings, mutation }
}

export function useModelPricingRows(enabled: boolean) {
    return useQuery({
        queryKey: modelPricingKey,
        queryFn: ({ signal }) => getModelPricingRows(signal),
        select: (rows) => new Map(rows.map(row => [row.model_id, row])),
        enabled,
        ...fresh,
    })
}

/** i18n key for a failed credit-pricing request; a version conflict gets its own wording. */
export function creditPricingErrorKey(reason: unknown): string {
    const key = getDshRequestErrorKey(reason)
    if (key === 'api_errors:26130') return 'dsh.pricing.conflict'
    return key ?? 'dsh.pricing.unavailable'
}
