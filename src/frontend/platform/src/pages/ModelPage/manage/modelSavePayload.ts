import type { ModelPricing } from "@/controllers/API/modelPricing";
import { hasDuplicateModelName } from "./modelNameTrim";
import { isPricingValid, samePrices } from "./modelPricing";

type SavedModel = {
    id?: number | string;
    model_name?: string | null;
    model_type?: string;
    config?: { voice?: string; pricing?: ModelPricing } & Record<string, unknown>;
};

/** The first problem that blocks saving, as an i18n key (the `model:` ones live outside `bs`). */
export function findModelError(models: SavedModel[]): string | null {
    if (models.some((model) => !model.model_name)) return "model.modelNameEmpty";
    if (models.some((model) => (model.model_name ?? "").length > 100)) return "model.modelNameLength";
    if (models.some((model) => !model.model_type)) return "model.modelNameValidation";
    if (hasDuplicateModelName(models)) return "model.modelDuplicate";
    if (models.some((model) => model.model_type === "tts" && !model.config?.voice)) return "model.voiceTypeRequired";
    const badPrice = models.some(
        (model) => model.model_type === "llm" && model.config?.pricing && !isPricingValid(model.config.pricing),
    );
    return badPrice ? "model:model.pricing.invalid" : null;
}

/** i18n key for an invalid provider name (bs namespace), or null when it is acceptable. */
export function providerNameErrorKey(name: string): string | null {
    if (!name) return "model.cannotBeEmpty";
    return name.length > 100 ? "model.max100Characters" : null;
}

/** The server's own message for a failed save; null when only the generic fallback is available. */
export function saveFailureMessage(error: unknown, generic: string): string | null {
    const reported = error && typeof error === "object" ? (error as { message?: unknown }).message : undefined;
    return typeof reported === "string" && reported.trim() && reported !== generic ? reported : null;
}

/** Prices as loaded from the server, keyed by model id. */
export function loadedPricing(models: SavedModel[] | undefined): Map<string, ModelPricing> {
    const prices = new Map<string, ModelPricing>();
    for (const model of models ?? []) {
        if (model.config?.pricing) prices.set(String(model.id), model.config.pricing);
    }
    return prices;
}

/**
 * Leave out prices the administrator did not change. The server then keeps the stored price,
 * so editing a model name or key never fails on a price another administrator updated meanwhile.
 */
export function withChangedPricing<T extends SavedModel>(models: T[], loaded: ReadonlyMap<string, ModelPricing>): T[] {
    return models.map((model) => {
        const pricing = model.config?.pricing;
        const before = loaded.get(String(model.id));
        if (!pricing || !before || !samePrices(pricing, before)) return model;
        const config = { ...model.config };
        delete config.pricing;
        return { ...model, config };
    });
}
