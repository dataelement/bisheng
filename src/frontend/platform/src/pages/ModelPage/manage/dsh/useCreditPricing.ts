import {
    getCreditSettings,
    getModelPricingRows,
    saveCreditSettings,
    saveModelPricing,
    type CreditSettings,
    type ModelPricing,
} from '@/controllers/API/modelPricing'
import { getDshRequestErrorKey } from '@/utils/dshRequestError'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { managementRequestScope } from '@/controllers/managementScope'
import { useContext } from 'react'
import { userContext } from '@/contexts/userContext'

const creditSettingsKey = ['dsh-credit-pricing', 'settings'] as const
const modelPricingKey = ['dsh-credit-pricing', 'models'] as const
function usePricingScope() {
    const { user } = useContext(userContext)
    return [user?.user_id, managementRequestScope()]
}
// Prices and ratios change from other pages (model configuration), so always read them fresh.
const fresh = { retry: false, cacheTime: 0, staleTime: 0, refetchOnWindowFocus: false } as const

/** The credit settings' USD/CNY rate for converting a model price between currencies (null until known). */
export function useUsdCnyRate(): { rate: string | null; unavailable: boolean } {
    const scope = usePricingScope()
    const settings = useQuery({
        queryKey: [...creditSettingsKey, ...scope],
        queryFn: ({ signal }) => getCreditSettings(signal),
        ...fresh,
    })
    return { rate: settings.data?.usd_cny_rate ?? null, unavailable: settings.isError }
}

export function useCreditSettings(enabled = true) {
    const client = useQueryClient()
    const scope = usePricingScope()
    const scopedKey = [...creditSettingsKey, ...scope]
    const settings = useQuery({
        queryKey: scopedKey,
        queryFn: ({ signal }) => getCreditSettings(signal),
        enabled,
        ...fresh,
    })
    const mutation = useMutation({
        mutationFn: (value: CreditSettings) => saveCreditSettings(value),
        retry: false,
        onSuccess: (value) => {
            client.setQueryData(scopedKey, value)
            // Ratios and converted prices depend on the base model, the currency and the rate.
            void client.invalidateQueries({ queryKey: modelPricingKey })
        },
    })
    return { settings, mutation }
}

export function useModelPricingRows(enabled: boolean) {
    const scope = usePricingScope()
    return useQuery({
        queryKey: [...modelPricingKey, ...scope],
        queryFn: ({ signal }) => getModelPricingRows(signal),
        select: (rows) => new Map(rows.map(row => [row.model_id, row])),
        enabled,
        ...fresh,
    })
}

export function useSaveModelPricing() {
    const client = useQueryClient()
    return useMutation({
        mutationFn: ({ modelId, pricing }: { modelId: number; pricing: ModelPricing }) => saveModelPricing(modelId, pricing),
        retry: false,
        // Refetch after a conflict too, so reopening the dialog shows the price that won.
        onSettled: () => void client.invalidateQueries({ queryKey: modelPricingKey }),
    })
}

/** i18n key for a failed credit-pricing request; a version conflict gets its own wording. */
export function creditPricingErrorKey(reason: unknown): string {
    const key = getDshRequestErrorKey(reason)
    if (key === 'api_errors:26130') return 'dsh.pricing.conflict'
    return key ?? 'dsh.pricing.unavailable'
}
