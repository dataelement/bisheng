/**
 * @jest-environment node
 */
/* eslint-disable no-restricted-syntax -- asserts that the hard-coded Chinese label is gone */
import { createInstance } from "i18next";
import { renderToStaticMarkup } from "react-dom/server";
import en from "~/locales/en/translation.json";
import ja from "~/locales/ja/translation.json";
import zh from "~/locales/zh-Hans/translation.json";
import ThinkingContent from "./ThinkingContent";

const mockI18n = createInstance();
jest.mock("~/hooks", () => ({ useLocalize: () => mockI18n.t.bind(mockI18n) }));
jest.mock("bisheng-icons", () => ({ Outlined: new Proxy({}, { get: () => () => null }) }));
// The component only reads one boolean from the store; keep the heavy store out of the test.
jest.mock("recoil", () => ({ useRecoilValue: () => false }));
jest.mock("~/store", () => ({ __esModule: true, default: { showThinking: "showThinking" } }));

beforeAll(async () => {
  await mockI18n.init({
    lng: "zh-Hans",
    resources: {
      "zh-Hans": { translation: zh },
      en: { translation: en },
      ja: { translation: ja },
    },
  });
});

const markup = () => renderToStaticMarkup(<ThinkingContent reasoning="some reasoning" />);

describe("ThinkingContent label", () => {
  it.each([
    ["zh-Hans", zh.com_ui_thoughts],
    ["en", en.com_ui_thoughts],
    ["ja", ja.com_ui_thoughts],
  ])("follows the interface language (%s)", async (lng, expected) => {
    await mockI18n.changeLanguage(lng);
    expect(markup()).toContain(`<span>${expected}</span>`);
  });

  it("is not the hard-coded Chinese label in English", async () => {
    await mockI18n.changeLanguage("en");
    expect(markup()).not.toContain("思考内容");
  });
});
