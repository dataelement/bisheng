import { render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import zh from "~/locales/zh-Hans/translation.json";
import { ChatErrorCard } from "./ChatErrorCard";

const mockI18n = createInstance();
jest.mock("~/hooks", () => ({ useLocalize: () => mockI18n.t.bind(mockI18n) }));
jest.mock("bisheng-icons", () => ({ Outlined: new Proxy({}, { get: () => () => null }) }));
jest.mock("~/components/ServiceBusyNotice", () => ({ ServiceBusyNotice: () => null }));

beforeAll(async () => {
  await mockI18n.init({ lng: "zh-Hans", resources: { "zh-Hans": { translation: zh } } });
});

describe("ChatErrorCard", () => {
  it("renders the dedicated copy for a truncated model output", () => {
    render(<ChatErrorCard errorType="output_truncated" />);
    expect(screen.getByText(zh.com_linsight_error_title_output_truncated)).toBeInTheDocument();
    expect(screen.getByText(zh.com_linsight_error_hint_output_truncated)).toBeInTheDocument();
  });
});
