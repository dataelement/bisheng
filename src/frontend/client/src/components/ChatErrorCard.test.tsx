import { fireEvent, render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import zh from "~/locales/zh-Hans/translation.json";
import apiErrors from "~/locales/zh-Hans/api_errors.gen.json";
import { ChatErrorCard } from "./ChatErrorCard";

const mockI18n = createInstance();
jest.mock("~/hooks", () => ({ useLocalize: () => mockI18n.t.bind(mockI18n) }));
jest.mock("bisheng-icons", () => ({
  Outlined: new Proxy({}, { get: () => () => null }),
  Filled: new Proxy({}, { get: () => () => null }),
}));
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

it('shows the model-service failure for a provider content filter with service provenance', () => {
    render(<ChatErrorCard errorType="content_filter" failureInfo={failureInfo} />);
    expect(screen.getByText(apiErrors.failure_model_service)).toBeInTheDocument();
    expect(screen.queryByText(zh.com_linsight_error_title_content_filter)).not.toBeInTheDocument();
    expect(screen.queryByText(zh.com_linsight_error_hint_content_filter)).not.toBeInTheDocument();
});

// 116 test, 2026-11-12: an AttributeError in the quota check rendered as
// "灵思Bisheng LLM相关错误" with nothing to look up. The umbrella codes keep the
// per-type copy, the reference id is shown, and the detail is one click away.
describe("unclassified task failure", () => {
    it.each([11090, 11091])("keeps the per-type description for umbrella code %s", (code) => {
        render(<ChatErrorCard errorType="unknown" errorCode={code} />);
        expect(screen.getByText(zh.com_linsight_error_desc_unknown)).toBeInTheDocument();
    });

    it("shows the reference id and the redacted detail behind a toggle", () => {
        const detail = "AttributeError: 'types.SimpleNamespace' object has no attribute 'sessions'";
        render(<ChatErrorCard errorType="unknown" errorCode={11091} referenceId="e5edb6dc55e04a8a" detail={detail} />);
        expect(screen.getByText(apiErrors.failure_id.replace("{{0}}", "e5edb6dc55e04a8a"))).toBeInTheDocument();
        expect(screen.queryByText(detail)).not.toBeInTheDocument();
        fireEvent.click(screen.getByText(zh.com_linsight_error_view_detail));
        expect(screen.getByText(detail)).toBeInTheDocument();
    });

    it("prefers the dependency failure id over the reference id", () => {
        render(<ChatErrorCard errorType="unknown" failureInfo={failureInfo} referenceId="other-ref" />);
        expect(screen.queryByText(apiErrors.failure_id.replace("{{0}}", "other-ref"))).not.toBeInTheDocument();
    });

    it("uses one disclosure for dependency metadata and redacted detail", () => {
        render(<ChatErrorCard errorType="unknown" failureInfo={failureInfo} detail="Redacted detail" />);
        expect(screen.getAllByText(zh.com_linsight_error_view_detail)).toHaveLength(1);
        expect(screen.queryByText("Redacted detail")).not.toBeInTheDocument();
        fireEvent.click(screen.getByText(zh.com_linsight_error_view_detail));
        expect(screen.getByText("Redacted detail")).toBeInTheDocument();
        expect(screen.getByText(/test-failure/)).toBeInTheDocument();
    });
});
