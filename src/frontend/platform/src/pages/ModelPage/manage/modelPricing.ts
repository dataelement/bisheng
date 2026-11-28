import type {
    ModelPricing,
    PriceCatalogEntry,
    PriceCatalogMatch,
    PricingCurrency,
} from "@/controllers/API/modelPricing";

// Same rule as the server: 0 to 999999.999999, at most six decimals, no sign or exponent.
export const PRICE_PATTERN = /^(0|[1-9]\d{0,5})(\.\d{1,6})?$/;
export const PRICE_FIELDS = ["input", "cache_read", "cache_write", "output"] as const;
export type PriceField = (typeof PRICE_FIELDS)[number];
export const PRICE_FIELD_LABELS: Record<PriceField, string> = {
    input: "model.pricing.input",
    cache_read: "model.pricing.cacheRead",
    cache_write: "model.pricing.cacheWrite",
    output: "model.pricing.output",
};

// One ordinary Q&A used for the "about N credits per question" estimate (3:1 like the ratio).
export const TYPICAL_INPUT_TOKENS = 3000;
export const TYPICAL_OUTPUT_TOKENS = 1000;

export const ZERO_PRICING: ModelPricing = {
    currency: "CNY",
    input: "0",
    cache_read: "0",
    cache_write: null,
    output: "0",
};

export function isValidPrice(value: string | null | undefined): boolean {
    return typeof value === "string" && PRICE_PATTERN.test(value);
}

/** Exact integer micro-units of a valid price string (fits a safe integer: < 1e12). */
export function priceMicro(value: string): number {
    const [whole, fraction = ""] = value.split(".");
    return Number(whole) * 1_000_000 + Number(fraction.padEnd(6, "0"));
}

/** Shortest decimal string of a micro-unit amount (10000 -> "0.01"), like the server's format_micro. */
export function formatMicro(value: number): string {
    const whole = Math.floor(value / 1_000_000);
    const fraction = String(value % 1_000_000).padStart(6, "0").replace(/0+$/, "");
    return fraction ? `${whole}.${fraction}` : String(whole);
}

/**
 * The credit value that keeps the same budget after the billing currency changes, rounded to
 * six decimals (half up). BigInt because value x rate can pass 2^53 at the range limits.
 */
export function convertCreditValue(
    value: string,
    from: PricingCurrency,
    to: PricingCurrency,
    usdCnyRate: string,
): string | null {
    if (!isValidPrice(value) || !isValidPrice(usdCnyRate) || !priceMicro(usdCnyRate)) return null;
    if (from === to) return value;
    const amount = BigInt(priceMicro(value));
    const rate = BigInt(priceMicro(usdCnyRate));
    const [numerator, denominator] = to === "USD" ? [amount * 1_000_000n, rate] : [amount * rate, 1_000_000n];
    return formatMicro(Number((numerator * 2n + denominator) / (denominator * 2n)));
}

/**
 * The same four prices in another currency at the credit settings' rate (six decimals, half up).
 * A price that is not a valid number yet is kept as typed; an empty cache-write price stays empty.
 */
export function convertPricing(pricing: ModelPricing, to: PricingCurrency, usdCnyRate: string): ModelPricing {
    const convert = (price: string) => convertCreditValue(price, pricing.currency, to, usdCnyRate) ?? price;
    return {
        currency: to,
        input: convert(pricing.input),
        cache_read: convert(pricing.cache_read),
        cache_write: pricing.cache_write ? convert(pricing.cache_write) : pricing.cache_write,
        output: convert(pricing.output),
    };
}

function effectiveCacheWrite(pricing: Pick<ModelPricing, "input" | "cache_write">): string {
    return pricing.cache_write == null || pricing.cache_write === "" ? pricing.input : pricing.cache_write;
}

export function isPricingValid(pricing: ModelPricing): boolean {
    return (
        isValidPrice(pricing.input) &&
        isValidPrice(pricing.cache_read) &&
        isValidPrice(pricing.output) &&
        (pricing.cache_write == null || pricing.cache_write === "" || isValidPrice(pricing.cache_write))
    );
}

/** Same currency and the same four prices (an empty cache-write price means the input price). */
export function samePrices(a: ModelPricing, b: ModelPricing): boolean {
    if (a.currency !== b.currency || !isPricingValid(a) || !isPricingValid(b)) return false;
    return (
        priceMicro(a.input) === priceMicro(b.input) &&
        priceMicro(a.cache_read) === priceMicro(b.cache_read) &&
        priceMicro(effectiveCacheWrite(a)) === priceMicro(effectiveCacheWrite(b)) &&
        priceMicro(a.output) === priceMicro(b.output)
    );
}

export function isFreePricing(pricing: ModelPricing): boolean {
    return isPricingValid(pricing) && [pricing.input, pricing.cache_read, effectiveCacheWrite(pricing), pricing.output]
        .every((price) => priceMicro(price) === 0);
}

export function pricingFromCatalog(entry: PriceCatalogEntry): ModelPricing {
    return {
        currency: entry.currency,
        input: entry.input,
        cache_read: entry.cache_read,
        cache_write: entry.cache_write,
        output: entry.output,
    };
}

/** Prices the administrator edits, keeping the server-owned revision for concurrent-edit checks. */
export function withPrices(current: ModelPricing | undefined, prices: ModelPricing): ModelPricing {
    return current?.revision ? { ...prices, revision: current.revision } : { ...prices };
}

export type PricingStatus = "catalog" | "review" | "edited" | "default" | "manual";

export function pricingStatus(pricing: ModelPricing, match: PriceCatalogMatch | null): PricingStatus {
    if (match?.entry) {
        if (!samePrices(pricing, pricingFromCatalog(match.entry))) return "edited";
        return match.via_name ? "review" : "catalog";
    }
    return isFreePricing(pricing) ? "default" : "manual";
}

/** Credits for one ordinary Q&A, from prices already in the billing currency. Display only. */
export function typicalCredits(
    prices: { input: string; output: string },
    creditValue: string,
): string | null {
    if (!isValidPrice(prices.input) || !isValidPrice(prices.output) || !isValidPrice(creditValue)) return null;
    const value = priceMicro(creditValue);
    if (!value) return null;
    const costMicro =
        (TYPICAL_INPUT_TOKENS * priceMicro(prices.input) + TYPICAL_OUTPUT_TOKENS * priceMicro(prices.output)) / 1_000_000;
    const credits = costMicro / value;
    if (credits === 0) return "0";
    if (credits < 0.01) return "<0.01";
    return credits < 1 ? credits.toFixed(2) : String(Math.round(credits * 100) / 100);
}

/** The ordinary-Q&A estimate for prices typed in either currency, converted like the server does. */
export function draftTypicalCredits(
    pricing: ModelPricing,
    settings: { currency: PricingCurrency; credit_value: string; usd_cny_rate: string },
): string | null {
    if (!isPricingValid(pricing)) return null;
    if (pricing.currency === settings.currency) return typicalCredits(pricing, settings.credit_value);
    const convert = (price: string) =>
        convertCreditValue(price, pricing.currency, settings.currency, settings.usd_cny_rate);
    const input = convert(pricing.input);
    const output = convert(pricing.output);
    return input && output ? typicalCredits({ input, output }, settings.credit_value) : null;
}
