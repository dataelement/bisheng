import { describe, expect, it } from "vitest";
import type { ModelPricing } from "@/controllers/API/modelPricing";
import { findModelError, loadedPricing, providerNameErrorKey, saveFailureMessage, withChangedPricing } from "./modelSavePayload";

const saved: ModelPricing = {
    currency: "CNY", input: "12", cache_read: "1.2", cache_write: null, output: "36", source: "CATALOG", revision: 2,
};
const llm = (id: number | string, pricing?: ModelPricing) => ({
    id, model_name: `model-${id}`, model_type: "llm", config: pricing ? { temperature: 0.2, pricing } : { temperature: 0.2 },
});

describe("saving model prices", () => {
    const baseline = loadedPricing([llm(7, saved), llm(8)]);

    it("leaves out prices nobody changed so the stored price and revision stay untouched", () => {
        const [model] = withChangedPricing([llm(7, { ...saved, input: "12.00" })], baseline);
        expect(model.config).toEqual({ temperature: 0.2 });
    });

    it("sends changed prices with the loaded revision and new models with their prefilled price", () => {
        const edited = { ...saved, output: "30" };
        const fresh = { currency: "USD" as const, input: "1", cache_read: "0.1", output: "4" };
        const [first, second] = withChangedPricing([llm(7, edited), llm("new-uuid", fresh)], baseline);
        expect(first.config.pricing).toEqual(edited);
        expect(second.config.pricing).toEqual(fresh);
    });

    it("blocks an invalid price before the request and keeps the existing checks first", () => {
        expect(findModelError([llm(7, { ...saved, input: "-1" })])).toBe("model:model.pricing.invalid");
        expect(findModelError([{ ...llm(7, { ...saved, input: "-1" }), model_name: "" }])).toBe("model.modelNameEmpty");
        expect(findModelError([{ ...llm(9), model_type: "embedding", config: { pricing: { ...saved, input: "x" } } }])).toBeNull();
        expect(findModelError([llm(7, saved), llm(8)])).toBeNull();
    });
});

describe("provider checks before saving", () => {
    it("names the provider-name problem", () => {
        expect(providerNameErrorKey("")).toBe("model.cannotBeEmpty");
        expect(providerNameErrorKey("x".repeat(101))).toBe("model.max100Characters");
        expect(providerNameErrorKey("OpenAI")).toBeNull();
    });

    it("shows the server message only when it says more than the generic fallback", () => {
        expect(saveFailureMessage({ message: "Price changed by someone else" }, "Request failed")).toBe("Price changed by someone else");
        expect(saveFailureMessage({ message: "Request failed" }, "Request failed")).toBeNull();
        expect(saveFailureMessage({ message: " " }, "Request failed")).toBeNull();
        expect(saveFailureMessage(null, "Request failed")).toBeNull();
    });
});
