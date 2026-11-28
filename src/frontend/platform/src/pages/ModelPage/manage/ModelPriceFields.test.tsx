import { act, fireEvent, render, screen, waitFor } from "@/test/test-utils";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ModelPricing, PriceCatalogEntry, PriceCatalogMatch } from "@/controllers/API/modelPricing";
import { ModelPriceFields } from "./ModelPriceFields";

const matchPriceCatalog = vi.fn();
const getCreditSettings = vi.fn();
vi.mock("@/controllers/API/modelPricing", () => ({
    matchPriceCatalog: (...args: unknown[]) => matchPriceCatalog(...args),
    getCreditSettings: (...args: unknown[]) => getCreditSettings(...args),
}));
const SETTINGS = { version: 1, currency: "CNY", credit_value: "0.01", usd_cny_rate: "6.72", base_model_id: null };

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
const found = (entry: PriceCatalogEntry | null, viaName = false): PriceCatalogMatch => ({
    matched: !!entry,
    via_name: viaName,
    catalog_version: "2026-11-10",
    entry,
});

function Harness({ initial, modelName = "qwen-max", onChange }: {
    initial?: ModelPricing
    modelName?: string
    onChange: (value: ModelPricing) => void
}) {
    const [value, setValue] = useState<ModelPricing | undefined>(initial);
    const [name, setName] = useState(modelName);
    return <>
        <button type="button" onClick={() => setName("qwen-plus")}>rename</button>
        <ModelPriceFields value={value} providerType="qwen" modelName={name}
            onChange={(next) => { setValue(next); onChange(next); }} />
    </>;
}

const field = (key: string) => screen.getByLabelText(key) as HTMLInputElement;

describe("model price fields", () => {
    beforeEach(() => {
        matchPriceCatalog.mockReset();
        getCreditSettings.mockReset().mockResolvedValue(SETTINGS);
    });

    it("fills a new model with the catalog price after the name settles", async () => {
        matchPriceCatalog.mockResolvedValue(found(QWEN_MAX));
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);
        await waitFor(() => expect(onChange).toHaveBeenCalledWith({
            currency: "CNY", input: "12", cache_read: "1.2", cache_write: "15", output: "36",
        }));
        expect(matchPriceCatalog).toHaveBeenCalledWith("qwen", "qwen-max", expect.any(AbortSignal));
        expect(field("model.pricing.output").value).toBe("36");
        expect(screen.getByText("model.pricing.statusCatalog")).toBeTruthy();
    });

    it("defaults an unknown model to free and says so", async () => {
        matchPriceCatalog.mockResolvedValue(found(null));
        const onChange = vi.fn();
        render(<Harness onChange={onChange} modelName="my-qwen" />);
        await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ input: "0", output: "0" })));
        expect(screen.getByText("model.pricing.defaultTag")).toBeTruthy();
    });

    it("never overwrites a saved price and offers to restore the list price", async () => {
        matchPriceCatalog.mockResolvedValue(found(QWEN_MAX));
        const onChange = vi.fn();
        const saved: ModelPricing = {
            currency: "CNY", input: "6", cache_read: "1.2", cache_write: "15", output: "36", source: "MANUAL", revision: 4,
        };
        render(<Harness initial={saved} onChange={onChange} />);
        const restore = await screen.findByRole("button", { name: "model.pricing.restore" });
        expect(onChange).not.toHaveBeenCalled();
        fireEvent.click(restore);
        expect(onChange).toHaveBeenLastCalledWith({
            currency: "CNY", input: "12", cache_read: "1.2", cache_write: "15", output: "36", revision: 4,
        });
    });

    it("stops prefilling once the administrator types and flags invalid prices", async () => {
        matchPriceCatalog.mockResolvedValue(found(QWEN_MAX));
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);
        await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
        fireEvent.change(field("model.pricing.input"), { target: { value: "1.0000001" } });
        expect(screen.getByRole("alert").textContent).toBe("model.pricing.invalid");
        onChange.mockClear();
        await act(async () => { fireEvent.click(screen.getByRole("button", { name: "rename" })); });
        await waitFor(() => expect(matchPriceCatalog).toHaveBeenCalledWith("qwen", "qwen-plus", expect.any(AbortSignal)));
        expect(onChange).not.toHaveBeenCalled();
        expect(field("model.pricing.input").value).toBe("1.0000001");
    });

    it("asks for a check when only the model name matched", async () => {
        matchPriceCatalog.mockResolvedValue(found(QWEN_MAX, true));
        render(<Harness onChange={vi.fn()} />);
        expect(await screen.findByText("model.pricing.statusReview")).toBeTruthy();
    });

    it("treats an empty cache-write price as the input price", async () => {
        matchPriceCatalog.mockResolvedValue(found(null));
        const onChange = vi.fn();
        render(<Harness onChange={onChange} modelName="my-qwen" />);
        await waitFor(() => expect(onChange).toHaveBeenCalled());
        fireEvent.change(field("model.pricing.cacheWrite"), { target: { value: "3" } });
        fireEvent.change(field("model.pricing.cacheWrite"), { target: { value: "" } });
        expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ cache_write: null }));
    });

    it("keeps working when the catalog cannot be reached", async () => {
        matchPriceCatalog.mockRejectedValue(new Error("offline"));
        const onChange = vi.fn();
        render(<Harness onChange={onChange} />);
        await waitFor(() => expect(matchPriceCatalog).toHaveBeenCalled());
        fireEvent.change(field("model.pricing.output"), { target: { value: "30" } });
        expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ output: "30" }));
    });
});

it("says nothing about the price list before a model name has been looked up", () => {
    matchPriceCatalog.mockReset();
    render(<Harness onChange={vi.fn()} modelName="" />);
    expect(screen.queryByText("model.pricing.defaultTag")).toBeNull();
    expect(screen.queryByText("model.pricing.statusDefault")).toBeNull();
    expect(matchPriceCatalog).not.toHaveBeenCalled();
    expect(screen.getByText("model.pricing.help")).toBeTruthy();
});

describe("switching the price currency", () => {
    const QWEN_MAX_CNY: ModelPricing = { currency: "CNY", input: "2.4", cache_read: "0.48", cache_write: "3", output: "9.6" };
    const prices = () => ["input", "cacheRead", "cacheWrite", "output"].map((key) => field(`model.pricing.${key}`).value);
    beforeEach(() => {
        matchPriceCatalog.mockReset().mockResolvedValue(found({ ...QWEN_MAX, ...QWEN_MAX_CNY }));
        getCreditSettings.mockReset().mockResolvedValue(SETTINGS);
    });

    it("converts the four prices at the credit settings' rate and restores them exactly on the way back", async () => {
        const onChange = vi.fn();
        render(<Harness initial={QWEN_MAX_CNY} onChange={onChange} />);
        const usd = screen.getByRole("radio", { name: "model.pricing.currencyUSD" });
        await waitFor(() => expect(usd).toBeEnabled());
        fireEvent.click(usd);
        // 2.4 / 6.72 = 0.357142857... -> six decimals, half up.
        expect(prices()).toEqual(["0.357143", "0.071429", "0.446429", "1.428571"]);
        expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ currency: "USD", input: "0.357143" }));
        expect(screen.getByText("model.pricing.converted")).toBeTruthy();
        // Back to CNY without editing: the original numbers, not 0.357143 x 6.72 = 2.400001.
        fireEvent.click(screen.getByRole("radio", { name: "model.pricing.currencyCNY" }));
        expect(prices()).toEqual(["2.4", "0.48", "3", "9.6"]);
        expect(screen.queryByText("model.pricing.converted")).toBeNull();
    });

    it("converts again from what was typed after a switch", async () => {
        render(<Harness initial={QWEN_MAX_CNY} onChange={vi.fn()} />);
        const usd = screen.getByRole("radio", { name: "model.pricing.currencyUSD" });
        await waitFor(() => expect(usd).toBeEnabled());
        fireEvent.click(usd);
        fireEvent.change(field("model.pricing.input"), { target: { value: "1" } });
        expect(screen.queryByText("model.pricing.converted")).toBeNull();
        fireEvent.click(screen.getByRole("radio", { name: "model.pricing.currencyCNY" }));
        expect(field("model.pricing.input").value).toBe("6.72");
    });

    it("puts the restore button next to the title and restores the official currency and prices", async () => {
        const onChange = vi.fn();
        render(<Harness initial={QWEN_MAX_CNY} onChange={onChange} />);
        const usd = screen.getByRole("radio", { name: "model.pricing.currencyUSD" });
        await waitFor(() => expect(usd).toBeEnabled());
        await screen.findByText("model.pricing.statusCatalog");
        expect(screen.queryByRole("button", { name: "model.pricing.restore" })).toBeNull();
        fireEvent.click(usd);
        const restore = screen.getByRole("button", { name: "model.pricing.restore" });
        expect(screen.getByText("model.pricing.title").parentElement).toContainElement(restore);
        fireEvent.click(restore);
        expect(onChange).toHaveBeenLastCalledWith(QWEN_MAX_CNY);
        expect(prices()).toEqual(["2.4", "0.48", "3", "9.6"]);
    });

    it("does not switch without a rate and says why", async () => {
        getCreditSettings.mockReset().mockRejectedValue(new Error("unavailable"));
        render(<Harness initial={QWEN_MAX_CNY} onChange={vi.fn()} />);
        expect(await screen.findByText("model.pricing.noRate")).toBeTruthy();
        expect(screen.getByRole("radio", { name: "model.pricing.currencyUSD" })).toBeDisabled();
        expect(prices()).toEqual(["2.4", "0.48", "3", "9.6"]);
    });
});
