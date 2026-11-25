import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { saveToolPricingApi } from '@/controllers/API/toolPricing'
import { Accordion } from '@/components/bs-ui/accordion'
import { ToolPriceDialog, estimateToolCharge } from './ToolPriceDialog'
import ToolItem from './ToolItem'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({
        t: (key: string, values?: Record<string, unknown>) =>
            values ? `${key}:${JSON.stringify(values)}` : key,
    }),
}))

vi.mock('@/controllers/API/toolPricing', async (importOriginal) => ({
    ...(await importOriginal<typeof import('@/controllers/API/toolPricing')>()),
    saveToolPricingApi: vi.fn(),
}))

const CREDIT_SETTING = {
    version: 1,
    currency: 'CNY' as const,
    credit_value: '0.01',
    usd_cny_rate: '7.0',
    base_model_id: null,
}

describe('ToolPriceDialog & ToolItem unified pricing', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    it('computes single-call credit estimate with integer ceil_div across currencies', () => {
        // USD 0.14 / 10 calls @ 7.0 rate -> 0.98 CNY / 10 = 0.098 CNY -> 9.8 credits -> ceil = 10 credits (approx 9.8 -> check exact micro)
        const res = estimateToolCharge({
            pricingMode: 'MONEY',
            currency: 'USD',
            price: '0.14',
            callCount: 10,
            creditSetting: CREDIT_SETTING,
        })
        expect(res.estimatedCredits).toBe('9.8')

        const ceilCheck = estimateToolCharge({
            pricingMode: 'CREDITS',
            currency: 'CNY',
            price: '10',
            callCount: 3,
            creditSetting: CREDIT_SETTING,
        })
        // 10_000_000 micro / 3 = 3_333_334 micro -> 3.333334
        expect(ceilCheck.estimatedCredits).toBe('3.333334')
    })

    it('validates inputs, defaults empty price to 0, and saves MONEY/CREDITS payload', async () => {
        const onSaved = vi.fn()
        const onClose = vi.fn()
        vi.mocked(saveToolPricingApi).mockResolvedValue({
            tool_id: 101,
            pricing_mode: 'MONEY',
            currency: 'USD',
            price: '0.02',
            price_micro: 20_000,
            call_count: 2,
            version: 1,
            estimated_credits: '7',
            estimated_cost: '0.07',
            effective_currency: 'CNY',
        })

        render(
            <ToolPriceDialog
                tool={{ id: 101, name: 'Web Search', tool_key: 'web_search' }}
                creditSetting={CREDIT_SETTING}
                onClose={onClose}
                onSaved={onSaved}
            />,
        )

        const callCountInput = screen.getByLabelText('pricing.callCount')
        const priceInput = screen.getByLabelText(/pricing\.price/)
        const saveBtn = screen.getByRole('button', { name: 'pricing.save' })

        // Invalid call_count disables save
        fireEvent.change(callCountInput, { target: { value: '0' } })
        expect(saveBtn).toBeDisabled()
        expect(screen.getByText('pricing.callCountInvalid')).toBeInTheDocument()

        // Invalid price decimals (> 6) disables save
        fireEvent.change(callCountInput, { target: { value: '2' } })
        fireEvent.change(priceInput, { target: { value: '1.1234567' } })
        expect(saveBtn).toBeDisabled()
        expect(screen.getByText('pricing.priceInvalid')).toBeInTheDocument()

        // Blank price treated as 0 and enabled
        fireEvent.change(priceInput, { target: { value: '' } })
        expect(saveBtn).toBeEnabled()

        // Valid input saves
        fireEvent.change(priceInput, { target: { value: '0.02' } })
        fireEvent.click(screen.getByRole('radio', { name: 'pricing.currencyUSD' }))
        fireEvent.click(saveBtn)

        await waitFor(() => {
            expect(saveToolPricingApi).toHaveBeenCalledWith(
                101,
                {
                    pricing_mode: 'MONEY',
                    currency: 'USD',
                    price: '0.02',
                    call_count: 2,
                    version: 0,
                },
                undefined,
            )
        })
        expect(onSaved).toHaveBeenCalledTimes(1)
        expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('renders 26130 optimistic-lock conflict message and triggers onConflict', async () => {
        const onConflict = vi.fn()
        vi.mocked(saveToolPricingApi).mockRejectedValue(
            Object.assign(new Error('conflict'), { statusCode: 26130, status_code: 26130 }),
        )

        render(
            <ToolPriceDialog
                tool={{ id: 101, name: 'Web Fetch', tool_key: 'web_fetch' }}
                item={{
                    tool_id: 101,
                    pricing_mode: 'CREDITS',
                    currency: null,
                    price: '5',
                    price_micro: 5_000_000,
                    call_count: 1,
                    version: 3,
                    estimated_credits: '5',
                    estimated_cost: '0.05',
                    effective_currency: 'CNY',
                }}
                creditSetting={CREDIT_SETTING}
                onClose={vi.fn()}
                onSaved={vi.fn()}
                onConflict={onConflict}
            />,
        )

        fireEvent.change(screen.getByLabelText(/pricing\.price/), { target: { value: '8' } })
        fireEvent.click(screen.getByRole('button', { name: 'pricing.save' }))

        await waitFor(() => {
            expect(screen.getByRole('alert')).toHaveTextContent('pricing.conflict')
        })
        expect(onConflict).toHaveBeenCalledTimes(1)
    })

    it('shows pricing column and gates set-price button by admin permission and master switch in ToolItem', () => {
        const groupData = {
            id: '1',
            name: 'Web Search',
            description: 'desc',
            children: [
                { id: 11, name: 'bing_search', tool_key: 'web_search', description: 'search', api_params: [] },
                { id: 12, name: 'free_tool', tool_key: 'free_tool', description: 'free', api_params: [] },
            ],
        }
        const pricingMap = {
            '11': {
                tool_id: 11,
                pricing_mode: 'MONEY' as const,
                currency: 'CNY' as const,
                price: '0.1',
                price_micro: 100_000,
                call_count: 1,
                version: 1,
                estimated_credits: '10',
                estimated_cost: '0.1',
                effective_currency: 'CNY' as const,
            },
        }
        const onSetPrice = vi.fn()

        // Admin with master switch ON
        const { rerender } = render(
            <Accordion type="single" defaultValue="1">
                <ToolItem
                    type="edit"
                    data={groupData}
                    showPricing
                    pricingMap={pricingMap}
                    onSetPrice={onSetPrice}
                />
            </Accordion>,
        )
        expect(screen.getByText(/pricing\.summaryMoney/)).toBeInTheDocument()
        expect(screen.getByText('pricing.free')).toBeInTheDocument()
        const editButtons = screen.getAllByRole('button', { name: 'pricing.setPrice' })
        expect(editButtons).toHaveLength(2)

        // Non-admin (onSetPrice null): price visible, edit button hidden
        rerender(
            <Accordion type="single" defaultValue="1">
                <ToolItem
                    type="edit"
                    data={groupData}
                    showPricing
                    pricingMap={pricingMap}
                    onSetPrice={null}
                />
            </Accordion>,
        )
        expect(screen.queryByRole('button', { name: 'pricing.setPrice' })).toBeNull()
        expect(screen.getByText('pricing.free')).toBeInTheDocument()

        // Master switch OFF (showPricing false): pricing hidden
        rerender(
            <Accordion type="single" defaultValue="1">
                <ToolItem
                    type="edit"
                    data={groupData}
                    showPricing={false}
                    pricingMap={pricingMap}
                    onSetPrice={null}
                />
            </Accordion>,
        )
        expect(screen.queryByText('pricing.free')).toBeNull()
    })
})
