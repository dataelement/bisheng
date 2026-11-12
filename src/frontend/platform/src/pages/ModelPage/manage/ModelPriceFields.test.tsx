import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ModelPricing, PriceCatalogEntry, PriceCatalogMatch } from "@/controllers/API/modelPricing";
import { ModelPriceFields } from "./ModelPriceFields";

const matchPriceCatalog = vi.fn();
vi.mock("@/controllers/API/modelPricing", () => ({
    matchPriceCatalog: (...args: unknown[]) => matchPriceCatalog(...args),
}));

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
