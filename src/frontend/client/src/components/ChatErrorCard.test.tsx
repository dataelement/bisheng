import { render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import zh from "~/locales/zh-Hans/translation.json";
import apiErrors from "~/locales/zh-Hans/api_errors.gen.json";
import { ChatErrorCard } from "./ChatErrorCard";

const mockI18n = createInstance();
jest.mock("~/hooks", () => ({ useLocalize: () => mockI18n.t.bind(mockI18n) }));
jest.mock("bisheng-icons", () => ({ Outlined: new Proxy({}, { get: () => () => null }) }));
jest.mock("~/components/ServiceBusyNotice", () => ({ ServiceBusyNotice: () => null }));

beforeAll(async () => {
  await mockI18n.init({ lng: "zh-Hans", resources: { "zh-Hans": { translation: { ...zh, api_errors: apiErrors } } } });
});

describe("ChatErrorCard", () => {
  it("renders the dedicated copy for a truncated model output", () => {
    render(<ChatErrorCard errorType="output_truncated" />);
    expect(screen.getByText(zh.com_linsight_error_title_output_truncated)).toBeInTheDocument();
    expect(screen.getByText(zh.com_linsight_error_hint_output_truncated)).toBeInTheDocument();
  });
});

const failureInfo = { version: 1, failure_id: 'test-failure', category: 'model_service', service: 'llm', occurred_at: '2026-11-10T08:00:00Z' };

it.each(['context_overflow', 'context_compress_failed', 'credit_exhausted'] as const)('retains actionable %s feedback alongside service provenance', (errorType) => {
    render(<ChatErrorCard errorType={errorType} failureInfo={failureInfo} />);
    expect(screen.getByText(zh[`com_linsight_error_title_${errorType}`])).toBeInTheDocument();
    expect(screen.getByText(zh[`com_linsight_error_hint_${errorType}`])).toBeInTheDocument();
    expect(screen.queryByText(apiErrors.failure_model_service)).not.toBeInTheDocument();
});

it('shows the fixed service title for a provider authentication failure', () => {
    render(<ChatErrorCard errorType="auth_error" failureInfo={failureInfo} />);
    expect(screen.getByText(apiErrors.failure_model_service)).toBeInTheDocument();
});
