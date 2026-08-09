import { getKnowledgeParseQueuePositionsApi } from "~/api/knowledge";
import { resolvePortalUploadSuccessMessage } from "./portalUploadQueueToast";

jest.mock("~/api/knowledge", () => ({
    getKnowledgeParseQueuePositionsApi: jest.fn(),
}));

describe("resolvePortalUploadSuccessMessage", () => {
    beforeEach(() => {
        jest.clearAllMocks();
    });

    test("splits queue-position lookups into batches of at most 100 file ids", async () => {
        const registeredFiles = Array.from({ length: 101 }, (_, index) => ({
            id: String(index + 1),
        })) as any;
        jest.mocked(getKnowledgeParseQueuePositionsApi)
            .mockResolvedValueOnce({
                items: [{ fileId: 1, state: "queued", aheadWaitingCount: 4 }],
                activeCount: 1,
                waitingCount: 105,
                approximate: true,
                asOf: "2026-08-09T00:00:00Z",
            })
            .mockResolvedValueOnce({
                items: [{ fileId: 101, state: "queued", aheadWaitingCount: 104 }],
                activeCount: 1,
                waitingCount: 105,
                approximate: true,
                asOf: "2026-08-09T00:00:00Z",
            });

        const message = await resolvePortalUploadSuccessMessage("space-1", registeredFiles);

        expect(getKnowledgeParseQueuePositionsApi).toHaveBeenCalledTimes(2);
        expect(getKnowledgeParseQueuePositionsApi).toHaveBeenNthCalledWith(
            1,
            "space-1",
            Array.from({ length: 100 }, (_, index) => index + 1),
        );
        expect(getKnowledgeParseQueuePositionsApi).toHaveBeenNthCalledWith(2, "space-1", [101]);
        expect(message).toBe("上传成功，101 个文件已进入队列，最前第 5/105 名");
    });
});
