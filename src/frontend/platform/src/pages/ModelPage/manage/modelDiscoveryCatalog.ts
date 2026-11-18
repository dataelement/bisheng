import type { DiscoveredModel } from "@/controllers/API/modelDiscovery";
import { getPriceCatalog } from "@/controllers/API/modelPricing";

/** Provider types with no vendor model list of their own: "选择模型" lists the price catalog instead. */
export const PRICE_CATALOG_ONLY = new Set(["openai_compatible"]);

/**
 * F016: price-catalog models for a provider type, grouped by vendor. A platform that resells
 * other vendors' models gets every entry, its own models first. Picking one fills the price
 * from the same catalog. The names are the catalog's, so the vendor's own naming still needs a
 * check.
 */
export async function priceCatalogModels(provider: string): Promise<DiscoveredModel[]> {
  const catalog = await getPriceCatalog();
  const own = catalog.entries.filter((entry) => entry.provider_types.includes(provider));
  const resold = catalog.multi_vendor_provider_types.includes(provider)
    ? catalog.entries.filter((entry) => !entry.provider_types.includes(provider))
    : [];
  return [...own, ...resold]
    .map((entry): DiscoveredModel => ({
      model_name: entry.aliases[0],
      display_name: entry.label,
      model_type: "llm",
      type_source: "registry",
      catalog: {
        vendor: entry.vendor,
        label: entry.label,
        currency: entry.currency,
        input: entry.input,
        output: entry.output,
      },
    }));
}
