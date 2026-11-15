import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { afterEach, expect, it, vi } from "vitest";
import enBs from "../../../../public/locales/en-US/bs.json";
import enModel from "../../../../public/locales/en-US/model.json";
import jaBs from "../../../../public/locales/ja/bs.json";
import jaModel from "../../../../public/locales/ja/model.json";
import zhBs from "../../../../public/locales/zh-Hans/bs.json";
import zhModel from "../../../../public/locales/zh-Hans/model.json";
import { ModelItem } from "./ModelItem";

vi.unmock("react-i18next");
afterEach(cleanup);
it.each([
  ["zh-Hans", zhBs, zhModel],
  ["en-US", enBs, enModel],
  ["ja", jaBs, jaModel],
] as const)(
  "shows advanced parameter guidance with actual %s resources",
  async (language, bs, model) => {
    const i18n = createInstance();
    await i18n
      .use(initReactI18next)
      .init({
        lng: language,
        defaultNS: "bs",
        fallbackLng: false,
        resources: { [language]: { bs, model } },
        interpolation: { escapeValue: false },
      });
    render(
      <I18nextProvider i18n={i18n}>
        <ModelItem
          type="qwen"
          data={{
            name: "Qwen",
            model_name: "qwen-max",
            model_type: "llm",
            config: { max_tokens: 20 },
          }}
          onInput={vi.fn()}
          onConfig={vi.fn()}
          onDelete={vi.fn()}
        />
      </I18nextProvider>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: model.model.configureModel }),
    );
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.getByRole("combobox")).toHaveTextContent("LLM");
    fireEvent.click(screen.getByRole("combobox"));
    for (const name of ["LLM", "Embedding", "Rerank", "ASR", "ASR RT", "TTS"]) {
      expect(screen.getByRole("option", { name })).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("option", { name: "LLM" }));
    expect(
      screen.getByRole("switch", { name: bs.model.webSearch }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: bs.model.advancedParamsConfig }),
    );
    expect(screen.getByText(model.model.advancedTokenHint)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("model.");
  },
);
