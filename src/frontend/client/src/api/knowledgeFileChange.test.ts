/** @jest-environment node */

import request from "./request";
import { getFileChangeDetailApi } from "./knowledge";

jest.mock("./request", () => ({
    __esModule: true,
    default: {
        get: jest.fn(),
    },
}));

const mockedRequest = request as jest.Mocked<typeof request>;

describe("file change API errors", () => {
    beforeEach(() => {
        jest.clearAllMocks();
    });

    it("rejects a business error instead of mapping its exception payload as detail", async () => {
        mockedRequest.get.mockResolvedValueOnce({
            status_code: 18073,
            status_message: "File change request does not exist or is not visible",
            data: {
                exception: "File change request does not exist or is not visible",
            },
        });

        await expect(getFileChangeDetailApi("81", 2)).rejects.toMatchObject({
            message: "File change request does not exist or is not visible",
            status_code: 18073,
        });
        expect(mockedRequest.get).toHaveBeenCalledWith(
            "/api/v1/knowledge/space/81/file-changes/2",
            { skip403Redirect: true },
        );
    });
});
