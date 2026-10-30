import { discoverModels } from "@/controllers/API/modelDiscovery";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../../../../public/locales/en-US/model.json";
import ja from "../../../../public/locales/ja/model.json";
import zh from "../../../../public/locales/zh-Hans/model.json";
import { ModelDiscovery } from "./ModelDiscovery";

vi.unmock("react-i18next");
vi.mock("@/controllers/API/modelDiscovery", () => ({
  discoverModels: vi.fn(),
}));

afterEach(cleanup);

describe("model discovery with actual language resources", () => {
  it.each([
    ["zh-Hans", zh],
    ["en-US", en],
    ["ja", ja],
  ] as const)(
    "renders labels, counts and API errors in %s",
    async (language, resource) => {
      const i18n = createInstance();
      await i18n.use(initReactI18next).init({
        lng: language,
        fallbackLng: false,
        defaultNS: "bs",
        resources: { [language]: { bs: {}, model: resource } },
        interpolation: { escapeValue: false },
      });
      vi.mocked(discoverModels).mockResolvedValue({
        models: [
          {
            model_name: "whisper-1",
            display_name: "Whisper",
            model_type: "asr",
            type_source: "registry",
          },
        ],
      });
      render(
        <I18nextProvider i18n={i18n}>
          <ModelDiscovery
            provider="openai"
            connectionVersion={0}
            autoFetchVersion={0}
            existing={[]}
            getConnection={() => ({
              provider: "openai",
              config: { openai_api_key: "fixture" },
            })}
            onImport={vi.fn()}
          />
        </I18nextProvider>,
      );
      fireEvent.click(
        screen.getByRole("button", { name: resource.model.selectModels }),
      );
      await screen.findByText("whisper-1");
      expect(screen.getAllByText("ASR").length).toBeGreaterThan(0);
      expect(
        screen.getByRole("dialog", { name: resource.model.selectModels }),
      ).toBeInTheDocument();
      expect(
        screen.getByText(
          i18n.t("model.discoveredCount", { ns: "model", count: 1 }),
        ),
      ).toBeInTheDocument();
      expect(
        screen.getByPlaceholderText(resource.model.searchDiscoveredModels),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("checkbox", { name: "whisper-1" }));
      expect(
        screen.getByRole("button", {
          name: i18n.t("model.addSelectedModels", { ns: "model", count: 1 }),
        }),
      ).toBeEnabled();
      vi.mocked(discoverModels).mockRejectedValue({
        response: { data: { data: { reason: "auth" } } },
      });
      fireEvent.click(
        screen.getByRole("button", { name: resource.model.refreshModels }),
      );
      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByRole("alert")).toHaveTextContent(
        resource.model.discoveryError_auth,
      );
      expect(document.body.textContent).not.toContain("model.");
    },
  );
});

it.each([
  ["zh-Hans", zh],
  ["en-US", en],
  ["ja", ja],
] as const)(
  "translates provider options and catalog source in %s",
  async (language, resource) => {
    const i18n = createInstance();
    await i18n
      .use(initReactI18next)
      .init({
        lng: language,
        fallbackLng: false,
        defaultNS: "bs",
        resources: { [language]: { bs: {}, model: resource } },
      });
    vi.mocked(discoverModels).mockResolvedValue({
      models: [],
      source: "live",
      scope: "deployments",
    });
    render(
      <I18nextProvider i18n={i18n}>
        <ModelDiscovery
          provider="volcengine"
          connectionVersion={0}
          autoFetchVersion={0}
          existing={[]}
          getConnection={() => ({ provider: "volcengine", config: {} })}
          onImport={vi.fn()}
        />
      </I18nextProvider>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: resource.model.selectModels }),
    );
    await screen.findByText(resource.model.discoveryScope_deployments);
    fireEvent.click(
      screen.getByRole("button", {
        name: resource.model.discoveryAdvancedSettings,
      }),
    );
    expect(
      screen.getByLabelText(resource.model.discoveryAccessKey),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("model.");
  },
);
