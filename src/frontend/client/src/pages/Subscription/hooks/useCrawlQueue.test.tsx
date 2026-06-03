import { act, renderHook, waitFor } from "@testing-library/react";
import { NotificationSeverity } from "~/common";
import { useCrawlQueue } from "./useCrawlQueue";

const mockShowToast = jest.fn();
const mockCrawlTempSourceApi = jest.fn();
const mockAddWebsiteSourceApi = jest.fn();

// p-limit ships as ESM and is not transformed by jest; replace it with a
// pass-through limiter that runs the task immediately.
jest.mock("p-limit", () => ({
    __esModule: true,
    default: () => (fn: () => unknown) => fn(),
}));

jest.mock("~/utils", () => ({
    generateUUID: () => "test-crawl-id",
}));

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock("~/Providers", () => ({
    useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("~/api/channels", () => ({
    crawlTempSourceApi: (...args: unknown[]) => mockCrawlTempSourceApi(...args),
    addWebsiteSourceApi: (...args: unknown[]) => mockAddWebsiteSourceApi(...args),
}));

describe("useCrawlQueue API-key limit handling", () => {
    beforeEach(() => {
        mockShowToast.mockClear();
        mockCrawlTempSourceApi.mockReset();
        mockAddWebsiteSourceApi.mockReset();
    });

    it("shows an error popup when crawl is rejected with the 19006 API-key limit code", async () => {
        mockCrawlTempSourceApi.mockResolvedValue({ status_code: 19006 });

        const { result } = renderHook(() => useCrawlQueue({ onSourceAdded: jest.fn() }));

        act(() => {
            result.current.enqueue("https://example.com");
        });

        await waitFor(() => {
            expect(mockShowToast).toHaveBeenCalledWith({
                message: "api_errors.19006",
                severity: NotificationSeverity.ERROR,
            });
        });
        // The site is never added once the account quota is exhausted.
        expect(mockAddWebsiteSourceApi).not.toHaveBeenCalled();
    });

    it("does not popup for per-site crawl failures (19003), which stay as queue tooltips", async () => {
        mockCrawlTempSourceApi.mockResolvedValue({ status_code: 19003 });

        const { result } = renderHook(() => useCrawlQueue({ onSourceAdded: jest.fn() }));

        act(() => {
            result.current.enqueue("https://example.com/article/123");
        });

        await waitFor(() => {
            expect(result.current.queue[0]?.status).toBe("failed");
        });
        expect(mockShowToast).not.toHaveBeenCalled();
    });
});
