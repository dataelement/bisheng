import { discoverModels, type DiscoveryConnection } from "@/controllers/API/modelDiscovery";
import { getPriceCatalog } from "@/controllers/API/modelPricing";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelDiscovery } from "./ModelDiscovery";

vi.mock("@/controllers/API/modelDiscovery", () => ({
  discoverModels: vi.fn(),
}));
vi.mock("@/controllers/API/modelPricing", () => ({
  getPriceCatalog: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const row = (model_name: string, catalog?: { vendor: string; label: string }) => ({
  model_name,
  display_name: model_name,
  model_type: "llm" as const,
  type_source: "registry" as const,
  ...(catalog ? { catalog: { ...catalog, currency: "USD" as const, input: "2", output: "8" } } : {}),
});
const gateway = { provider: "openai_compatible", config: { openai_api_base: "https://gateway.example/v1" } };
const props = (getConnection: (quiet?: boolean) => DiscoveryConnection | null) => ({
  provider: "openai_compatible",
  connectionVersion: 0,
  existing: [],
  getConnection: vi.fn(getConnection),
  onImport: vi.fn(),
});

describe("vendor-listed models with catalog prices", () => {
  beforeEach(() => {
    vi.mocked(discoverModels).mockReset();
    vi.mocked(getPriceCatalog).mockReset().mockResolvedValue({
      version: "2026-11-16",
      multi_vendor_provider_types: ["openai_compatible"],
      entries: [
        {
          key: "openai/gpt-4.1",
          vendor: "OpenAI",
          label: "GPT-4.1",
          provider_types: ["openai", "openai_compatible"],
          aliases: ["gpt-4.1"],
          currency: "USD",
          input: "2",
          cache_read: "0.5",
          cache_write: null,
          output: "8",
          source_url: "https://example.com",
          verified_at: "2026-11-16",
        },
      ],
    });
  });

  it("lists a gateway's own models first, priced from the catalog or marked as added at 0", async () => {
    vi.mocked(discoverModels).mockResolvedValue({
      models: [row("openai/gpt-4.1", { vendor: "OpenAI", label: "GPT-4.1" }), row("private-model")],
      source: "live",
      scope: "catalog",
    });
    const input = props(() => gateway);
    render(<ModelDiscovery {...input} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("private-model");
    expect(discoverModels).toHaveBeenCalledWith({ ...gateway, source: "auto", options: {} });
    expect(getPriceCatalog).not.toHaveBeenCalled();
    expect(screen.getAllByText("model.catalogPrice")).toHaveLength(1);
    expect(screen.getAllByText("model.catalogPriceMissing")).toHaveLength(1);
    // Vendor headers belong to the catalog list only.
    expect(screen.queryByText("OpenAI")).toBeNull();
    expect(screen.getByText("model.discoveryScope_catalog")).toBeInTheDocument();
  });

  it("falls back to the price catalog with the reason when the gateway list fails", async () => {
    vi.mocked(discoverModels).mockRejectedValue({ data: { reason: "auth" } });
    render(<ModelDiscovery {...props(() => gateway)} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("gpt-4.1");
    expect(screen.getByText("model.discoveryError_auth")).toBeInTheDocument();
    expect(screen.getByText("model.discoveryScope_price_catalog")).toBeInTheDocument();
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
  });

  it("lists the price catalog quietly while the gateway address is still empty", async () => {
    const input = props(() => null);
    render(<ModelDiscovery {...input} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("gpt-4.1");
    expect(input.getConnection).toHaveBeenCalledWith(true);
    expect(input.getConnection).not.toHaveBeenCalledWith();
    expect(discoverModels).not.toHaveBeenCalled();
  });

  it("does not mark self-hosted models as unpriced", async () => {
    vi.mocked(discoverModels).mockResolvedValue({ models: [row("qwen3-local")], source: "live", scope: "local" });
    const input = { ...props(() => ({ provider: "vllm", config: {} })), provider: "vllm" };
    render(<ModelDiscovery {...input} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("qwen3-local");
    expect(screen.queryByText("model.catalogPriceMissing")).toBeNull();
  });
});
