import { discoverModels } from "@/controllers/API/modelDiscovery";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ModelDiscovery } from "./ModelDiscovery";

vi.mock("@/controllers/API/modelDiscovery", () => ({
  discoverModels: vi.fn(),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const catalog = [
  {
    model_name: "gpt-4o",
    display_name: "GPT",
    model_type: "llm" as const,
    type_source: "registry" as const,
  },
  {
    model_name: "whisper-1",
    display_name: "Whisper",
    model_type: "asr" as const,
    type_source: "registry" as const,
  },
  {
    model_name: "private",
    display_name: "Private",
    model_type: null,
    type_source: "unknown" as const,
  },
];
const props = () => ({
  provider: "openai",
  connectionVersion: 0,
  autoFetchVersion: 0,
  existing: ["gpt-4o"],
  getConnection: () => ({
    provider: "openai",
    config: { openai_api_key: "test" },
  }),
  onImport: vi.fn(),
});

describe("model discovery interaction", () => {
  beforeEach(() => {
    vi.mocked(discoverModels).mockReset();
  });
  it("fetches, preserves existing models and fills only selected models", async () => {
    vi.mocked(discoverModels).mockResolvedValue({ models: catalog });
    const input = props();
    render(<ModelDiscovery {...input} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("whisper-1");
    expect(screen.getByRole("checkbox", { name: "gpt-4o" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "private" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "whisper-1" }));
    fireEvent.click(
      screen.getByRole("button", { name: "model.addSelectedModels" }),
    );
    expect(input.onImport).toHaveBeenCalledWith([catalog[1]]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText("whisper-1")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    expect(screen.getByText("whisper-1")).toBeInTheDocument();
    expect(discoverModels).toHaveBeenCalledTimes(1);
  });
  it("discards responses after the connection changes", async () => {
    let resolve: (value: { models: typeof catalog }) => void;
    vi.mocked(discoverModels).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const input = props();
    const view = render(<ModelDiscovery {...input} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    view.rerender(<ModelDiscovery {...input} connectionVersion={1} />);
    await act(async () => {
      resolve({ models: catalog });
    });
    expect(screen.queryByText("whisper-1")).toBeNull();
    expect(
      screen.getByRole("button", { name: "model.selectModels" }),
    ).toBeEnabled();
  });
  it("automatically fetches on completed input blur and avoids duplicate blur requests", async () => {
    vi.mocked(discoverModels).mockResolvedValue({ models: [] });
    const input = props();
    const view = render(<ModelDiscovery {...input} autoFetchVersion={1} />);
    await waitFor(() => expect(discoverModels).toHaveBeenCalledTimes(1));
    view.rerender(<ModelDiscovery {...input} autoFetchVersion={2} />);
    expect(discoverModels).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByText("model.emptyModelCatalog"),
    ).toBeInTheDocument();
  });
  it("shows recoverable authentication feedback and permits a retry", async () => {
    vi.mocked(discoverModels).mockImplementation(async () => {
      throw Object.assign(new Error("auth fixture"), {
        response: { data: { data: { reason: "auth" } } },
      });
    });
    render(<ModelDiscovery {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "model.discoveryError_auth",
    );
    expect(
      screen.getByRole("button", { name: "model.refreshModels" }),
    ).toBeEnabled();
  });
  it("keeps selections while the picker is closed and imports only after confirmation", async () => {
    vi.mocked(discoverModels).mockResolvedValue({ models: catalog });
    const input = props();
    render(<ModelDiscovery {...input} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("whisper-1");
    fireEvent.click(screen.getByRole("checkbox", { name: "whisper-1" }));
    fireEvent.click(screen.getByRole("button", { name: "model.cancel" }));
    expect(screen.queryByText("whisper-1")).toBeNull();
    expect(input.onImport).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    expect(screen.getByRole("checkbox", { name: "whisper-1" })).toBeChecked();
  });
  it("selects only eligible search results and preserves hidden selections", async () => {
    vi.mocked(discoverModels).mockResolvedValue({
      models: [
        ...catalog,
        {
          model_name: "other-llm",
          display_name: "Other",
          model_type: "llm",
          type_source: "registry",
        },
        {
          model_name: "image-model",
          display_name: "Image",
          model_type: null,
          type_source: "unsupported",
        },
      ],
    });
    const input = props();
    render(<ModelDiscovery {...input} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("whisper-1");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "whisper" },
    });
    fireEvent.click(
      screen.getByRole("checkbox", { name: "model.selectVisibleModels" }),
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "other" },
    });
    fireEvent.click(
      screen.getByRole("checkbox", { name: "model.selectVisibleModels" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "model.addSelectedModels" }),
    );
    expect(
      input.onImport.mock.calls[0][0].map(
        (model: { model_name: string }) => model.model_name,
      ),
    ).toEqual(["whisper-1", "other-llm"]);
  });
  it("shows recognized types as labels and requires confirmation for unknown types", async () => {
    vi.mocked(discoverModels).mockResolvedValue({ models: catalog });
    render(<ModelDiscovery {...props()} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("whisper-1");
    expect(screen.getByText("model.type_asr")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("combobox", { name: "model.confirmModelTypeFor" }),
    );
    fireEvent.click(
      screen.getByRole("option", { name: "model.type_embedding" }),
    );
    expect(screen.getByRole("checkbox", { name: "private" })).toBeEnabled();
    fireEvent.click(
      screen.getByRole("combobox", { name: "model.filterModelType" }),
    );
    fireEvent.click(screen.getByRole("option", { name: "model.type_asr" }));
    expect(screen.getByText("whisper-1")).toBeInTheDocument();
    expect(screen.queryByText("private")).toBeNull();
  });
});

describe("provider-specific discovery", () => {
  beforeEach(() => {
    vi.mocked(discoverModels).mockReset();
  });

  it.each([
    "azure_openai",
    "volcengine",
    "tencent",
    "spark",
    "minimax",
    "zhipu",
  ])("opens the picker for %s", async (provider) => {
    vi.mocked(discoverModels).mockResolvedValue({ models: [], source: "live" });
    render(
      <ModelDiscovery
        {...props()}
        provider={provider}
        getConnection={() => ({ provider, config: {} })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await waitFor(() =>
      expect(discoverModels).toHaveBeenCalledWith({
        provider,
        config: {},
        source: "auto",
        options: {},
      }),
    );
  });

  it("labels preset catalogs and clears selections when the source changes", async () => {
    vi.mocked(discoverModels).mockResolvedValue({
      models: catalog,
      source: "preset",
      catalog_date: "2026-10-21",
      docs_url: "https://docs.example/models",
    });
    render(<ModelDiscovery {...props()} provider="zhipu" existing={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("model.discoveryPresetNotice");
    expect(
      screen.getByRole("link", { name: "model.discoveryDocs" }),
    ).toHaveAttribute("href", "https://docs.example/models");
    fireEvent.click(screen.getByRole("checkbox", { name: "gpt-4o" }));
    fireEvent.click(
      screen.getByRole("button", { name: "model.discoveryAdvancedSettings" }),
    );
    fireEvent.click(
      screen.getByRole("combobox", { name: "model.discoverySource" }),
    );
    fireEvent.click(
      screen.getByRole("option", { name: "model.discoverySourceLive" }),
    );
    expect(screen.queryByText("gpt-4o")).toBeNull();
    expect(
      screen.getByRole("button", { name: "model.addSelectedModels" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "model.refreshModels" }),
    );
    await waitFor(() =>
      expect(discoverModels).toHaveBeenLastCalledWith(
        expect.objectContaining({ source: "live" }),
      ),
    );
  });

  it("sends request-only credentials and clears them when closed", async () => {
    vi.mocked(discoverModels).mockResolvedValue({
      models: [],
      source: "live",
      scope: "deployments",
    });
    render(<ModelDiscovery {...props()} provider="volcengine" />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("model.emptyModelCatalog");
    fireEvent.click(
      screen.getByRole("button", { name: "model.discoveryAdvancedSettings" }),
    );
    fireEvent.change(screen.getByLabelText("model.discoveryAccessKey"), {
      target: { value: "ak-fixture" },
    });
    fireEvent.change(screen.getByLabelText("model.discoverySecretKey"), {
      target: { value: "sk-fixture" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "model.refreshModels" }),
    );
    await waitFor(() =>
      expect(discoverModels).toHaveBeenLastCalledWith(
        expect.objectContaining({
          options: {
            access_key_id: "ak-fixture",
            secret_access_key: "sk-fixture",
          },
        }),
      ),
    );
    await screen.findByText("model.emptyModelCatalog");
    fireEvent.click(screen.getByRole("button", { name: "model.cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    fireEvent.click(
      screen.getByRole("button", { name: "model.discoveryAdvancedSettings" }),
    );
    expect(screen.getByLabelText("model.discoveryAccessKey")).toHaveValue("");
    expect(screen.getByLabelText("model.discoverySecretKey")).toHaveValue("");
  });

  it("requires Azure deployment names before importing model catalog entries", async () => {
    vi.mocked(discoverModels).mockResolvedValue({
      models: [catalog[0]],
      source: "live",
      scope: "azure_models",
    });
    const input = props();
    render(<ModelDiscovery {...input} provider="azure_openai" existing={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("gpt-4o");
    expect(screen.getByRole("checkbox", { name: "gpt-4o" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("model.discoveryDeploymentFor"), {
      target: { value: "production-chat" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "gpt-4o" }));
    fireEvent.click(
      screen.getByRole("button", { name: "model.addSelectedModels" }),
    );
    expect(input.onImport).toHaveBeenCalledWith([
      { ...catalog[0], model_name: "production-chat" },
    ]);
  });

  it("invalidates a pending response when management options change", async () => {
    let resolve!: (value: { models: typeof catalog }) => void;
    vi.mocked(discoverModels).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    render(<ModelDiscovery {...props()} provider="volcengine" />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    fireEvent.click(
      screen.getByRole("button", { name: "model.discoveryAdvancedSettings" }),
    );
    fireEvent.change(screen.getByLabelText("model.discoveryAccessKey"), {
      target: { value: "changed" },
    });
    await act(async () => resolve({ models: catalog }));
    expect(screen.queryByText("whisper-1")).toBeNull();
  });
});

describe("progressive model discovery", () => {
  beforeEach(() => {
    vi.mocked(discoverModels).mockReset();
  });

  it.each(["qwen", "volcengine", "azure_openai", "zhipu"])(
    "keeps %s extra settings hidden on automatic fetch",
    async (provider) => {
      vi.mocked(discoverModels).mockResolvedValue({
        models: [],
        source: "live",
      });
      render(
        <ModelDiscovery
          {...props()}
          provider={provider}
          autoFetchVersion={1}
        />,
      );
      await screen.findByText("model.emptyModelCatalog");
      expect(
        screen.queryByRole("combobox", { name: "model.discoverySource" }),
      ).toBeNull();
      expect(screen.queryByLabelText("model.discoveryWorkspace")).toBeNull();
      expect(screen.queryByLabelText("model.discoveryAccessKey")).toBeNull();
      expect(screen.queryByLabelText("model.discoveryResourceId")).toBeNull();
      expect(discoverModels).toHaveBeenCalledWith(
        expect.objectContaining({ source: "auto", options: {} }),
      );
    },
  );

  it("requests only a missing workspace and hides it after a successful retry", async () => {
    vi.mocked(discoverModels).mockRejectedValueOnce({
      response: { data: { data: { reason: "workspace" } } },
    });
    vi.mocked(discoverModels).mockResolvedValue({
      models: catalog,
      source: "live",
    });
    render(<ModelDiscovery {...props()} provider="qwen" />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByLabelText("model.discoveryWorkspace");
    expect(screen.queryByLabelText("model.discoveryCatalogUrl")).toBeNull();
    fireEvent.change(screen.getByLabelText("model.discoveryWorkspace"), {
      target: { value: "workspace-test" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "model.refreshModels" }),
    );
    await screen.findByText("whisper-1");
    expect(discoverModels).toHaveBeenLastCalledWith(
      expect.objectContaining({ options: { workspace_id: "workspace-test" } }),
    );
    expect(screen.queryByLabelText("model.discoveryWorkspace")).toBeNull();
  });

  it("shows required management credentials after an unsupported list route", async () => {
    vi.mocked(discoverModels).mockRejectedValueOnce({ response: { data: { data: { reason: "credentials" } } } });
    render(<ModelDiscovery {...props()} provider="volcengine" />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByLabelText("model.discoveryAccessKey");
    expect(screen.getByLabelText("model.discoverySecretKey")).toBeInTheDocument();
    expect(screen.queryByLabelText("model.discoverySessionToken")).toBeNull();
    expect(screen.queryByRole("combobox", { name: "model.discoverySource" })).toBeNull();
  });

  it("keeps credentials hidden for an authentication error", async () => {
    vi.mocked(discoverModels).mockRejectedValue({
      response: { data: { data: { reason: "auth" } } },
    });
    render(<ModelDiscovery {...props()} provider="volcengine" />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "model.discoveryError_auth",
    );
    expect(screen.queryByLabelText("model.discoveryAccessKey")).toBeNull();
  });

  it("discards a late missing-information response after closing", async () => {
    let reject!: (error: unknown) => void;
    vi.mocked(discoverModels).mockReturnValueOnce(
      new Promise((_, fail) => {
        reject = fail;
      }),
    );
    render(<ModelDiscovery {...props()} provider="qwen" />);
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    fireEvent.click(screen.getByRole("button", { name: "model.cancel" }));
    await act(async () =>
      reject({ response: { data: { data: { reason: "workspace" } } } }),
    );
    vi.mocked(discoverModels).mockResolvedValue({ models: [], source: "live" });
    fireEvent.click(screen.getByRole("button", { name: "model.selectModels" }));
    await screen.findByText("model.emptyModelCatalog");
    expect(screen.queryByLabelText("model.discoveryWorkspace")).toBeNull();
  });
});
