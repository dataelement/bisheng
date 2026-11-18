import { describe, expect, it } from "vitest";
import type { PriceCatalogEntry, PriceCatalogMatch } from "@/controllers/API/modelPricing";
import {
    ZERO_PRICING,
    convertCreditValue,
    formatMicro,
    isFreePricing,
    isPricingValid,
    isValidPrice,
    priceMicro,
    pricingFromCatalog,
    pricingStatus,
    samePrices,
    typicalCredits,
    withPrices,
} from "./modelPricing";

const QWEN_MAX: PriceCatalogEntry = {
    key: "qwen/qwen-max",
    vendor: "Alibaba Cloud",
    label: "Qwen Max",
    provider_types: ["qwen"],
    aliases: ["qwen-max"],
    currency: "CNY",
    input: "12",
    cache_read: "1.2",
    cache_write: "15",
    output: "36",
    source_url: "https://help.aliyun.com/zh/model-studio/model-pricing",
    verified_at: "2026-11-10",
};

const match = (entry: PriceCatalogEntry | null, viaName = false): PriceCatalogMatch => ({
    matched: !!entry,
    via_name: viaName,
    catalog_version: "2026-11-10",
    entry,
});

describe("model price strings", () => {
    it.each(["0", "9", "0.3", "999999.999999", "0.000001"])("accepts %s", (value) => {
        expect(isValidPrice(value)).toBe(true);
    });

    it.each(["-1", "1.0000001", "1000000", "01", "1.", ".5", "1e3", " 1", ""])("rejects %s", (value) => {
        expect(isValidPrice(value)).toBe(false);
    });

    it("converts exactly to micro-units", () => {
        expect(priceMicro("0.3")).toBe(300_000);
        expect(priceMicro("999999.999999")).toBe(999_999_999_999);
    });
});

describe("comparing prices", () => {
    it("treats an empty cache-write price as the input price and ignores trailing zeros", () => {
        const deepseek = { currency: "CNY" as const, input: "9", cache_read: "0.3", cache_write: null, output: "27" };
        expect(samePrices(deepseek, { ...deepseek, input: "9.000", cache_write: "9" })).toBe(true);
        expect(samePrices(deepseek, { ...deepseek, currency: "USD" })).toBe(false);
        expect(samePrices(deepseek, { ...deepseek, output: "27.1" })).toBe(false);
    });

    it("recognises free models", () => {
        expect(isFreePricing(ZERO_PRICING)).toBe(true);
        expect(isFreePricing({ ...ZERO_PRICING, cache_write: "0.1" })).toBe(false);
        expect(isPricingValid({ ...ZERO_PRICING, output: "abc" })).toBe(false);
    });
});

describe("price source shown to administrators", () => {
    const catalog = pricingFromCatalog(QWEN_MAX);

    it("marks catalog prices, edited prices and name-only matches", () => {
        expect(pricingStatus(catalog, match(QWEN_MAX))).toBe("catalog");
        expect(pricingStatus(catalog, match(QWEN_MAX, true))).toBe("review");
        expect(pricingStatus({ ...catalog, input: "6" }, match(QWEN_MAX))).toBe("edited");
    });

    it("marks unmatched zero prices as the free default and other prices as manual", () => {
        expect(pricingStatus(ZERO_PRICING, match(null))).toBe("default");
        expect(pricingStatus({ ...ZERO_PRICING, input: "2" }, match(null))).toBe("manual");
    });

    it("keeps the stored revision when prices are edited", () => {
        expect(withPrices({ ...catalog, revision: 3 }, { ...catalog, input: "6" })).toEqual({ ...catalog, input: "6", revision: 3 });
        expect(withPrices(undefined, catalog)).toEqual(catalog);
    });
});

describe("one ordinary question", () => {
    it("estimates credits from 3,000 input and 1,000 output tokens", () => {
        // 3,000 x 9 + 1,000 x 27 = 54,000 micro-yuan = 0.054 yuan = 5.4 credits at 0.01
        expect(typicalCredits({ input: "9", output: "27" }, "0.01")).toBe("5.4");
        expect(typicalCredits({ input: "0.2", output: "0.8" }, "0.01")).toBe("0.14");
        expect(typicalCredits({ input: "0", output: "0" }, "0.01")).toBe("0");
        expect(typicalCredits({ input: "0.000001", output: "0" }, "0.01")).toBe("<0.01");
        expect(typicalCredits({ input: "9", output: "27" }, "bad")).toBeNull();
    });
});

describe("credit value across currencies", () => {
    it("formats micro-units like the server", () => {
        expect(formatMicro(10_000)).toBe("0.01");
        expect(formatMicro(1_500_000)).toBe("1.5");
        expect(formatMicro(1_000_000)).toBe("1");
        expect(formatMicro(0)).toBe("0");
    });

    it("keeps the budget when the billing currency changes, rounding to six decimals", () => {
        // 0.01 yuan / 7.2 = 0.0013888... dollars
        expect(convertCreditValue("0.01", "CNY", "USD", "7.2")).toBe("0.001389");
        expect(convertCreditValue("0.001389", "USD", "CNY", "7.2")).toBe("0.010001");
        expect(convertCreditValue("100", "USD", "CNY", "100")).toBe("10000");
        expect(convertCreditValue("0.01", "CNY", "CNY", "7.2")).toBe("0.01");
    });

    it("refuses to convert unusable input", () => {
        expect(convertCreditValue("abc", "CNY", "USD", "7.2")).toBeNull();
        expect(convertCreditValue("0.01", "CNY", "USD", "0")).toBeNull();
    });
});
