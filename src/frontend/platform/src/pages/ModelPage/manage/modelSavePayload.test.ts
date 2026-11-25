import { describe, expect, it } from "vitest";
import type { ModelPricing } from "@/controllers/API/modelPricing";
import { changedPrices, findModelError, loadedPricing, providerNameErrorKey, saveFailureMessage, withChangedPricing } from "./modelSavePayload";
import { nextModelName } from "./modelNameTrim";

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

describe("price changes to confirm before saving", () => {
    const saved: ModelPricing = { currency: "CNY", input: "2.4", cache_read: "0.48", cache_write: null, output: "9.6", revision: 2 };
    it("lists only saved models whose price changed, named for the administrator", () => {
        const loaded = loadedPricing([{ id: 1, config: { pricing: saved } }, { id: 2, config: { pricing: saved } }]);
        const changes = changedPrices([
            { id: 1, name: "Qwen Max", model_name: "qwen-max", config: { pricing: { ...saved, output: "12" } } },
            { id: 2, name: "qwen-plus", model_name: "qwen-plus", config: { pricing: { ...saved, cache_write: "2.4" } } },
            { id: "new-row", name: "new", model_name: "glm-5.3", config: { pricing: { ...saved, input: "8" } } },
        ], loaded);
        // Row 2 only spells out the default cache-write price; the new row has no saved price to compare.
        expect(changes).toEqual([{ name: "Qwen Max (qwen-max)", before: saved, after: { ...saved, output: "12" } }]);
    });
});

describe("default name of an added model", () => {
    it("is one past the highest model N", () => {
        expect(nextModelName([])).toBe("model 1");
        expect(nextModelName([{ name: "model 2" }, { name: "GPT" }, { name: "model 7" }])).toBe("model 8");
    });
});
